from collections import defaultdict
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import lldb

from .libc.abi import ABI, LibcABI

if TYPE_CHECKING:
    from .core import Tracer

# Global singleton instance of the hooker
hooker: Optional["LibcFunctionHooker"] = None


# These global functions are required for LLDB's `SetScriptCallbackFunction`,
# which resolves function names from the global script context.
def libc_breakpoint_callback(
    frame: lldb.SBFrame, bp_loc: lldb.SBBreakpointLocation, extra_args: Any, internal_dict: Dict[str, Any]
) -> bool:
    """Global callback for libc function entry breakpoints."""
    if hooker:
        hooker.handle_function_entry(frame)
    return False  # Always continue execution


def libc_return_callback(
    frame: lldb.SBFrame, bp_loc: lldb.SBBreakpointLocation, extra_args: Any, internal_dict: Dict[str, Any]
) -> bool:
    """Global callback for libc function return breakpoints."""
    if hooker:
        hooker.handle_function_return(frame, bp_loc)
    return False  # Always continue execution


def prepare_hooker(tracer: "Tracer") -> "LibcFunctionHooker":
    """Initializes and returns the global LibcFunctionHooker instance."""
    global hooker
    if hooker is None:
        hooker = LibcFunctionHooker(tracer)
        hooker.setup_hooks()
    return hooker


def get_libc_hooker() -> Optional["LibcFunctionHooker"]:
    """Gets the global hooker instance."""
    return hooker


class LibcFunctionHooker:
    """
    Handles the hooking of libc functions to trace their calls, arguments,
    and return values.
    """

    def __init__(self, tracer: "Tracer"):
        self.tracer = tracer
        self.logger = tracer.logger
        self.target = tracer.target
        self.abi_type = ABI.get_platform_abi(self.target)
        self.libc_abi = LibcABI(self.target)

        # State tracking
        # {thread_id: [(func_name, return_bp_id)]}
        self.function_stacks: Dict[int, List[Tuple[str, int]]] = defaultdict(list)
        self.async_callbacks: List[Callable] = []

        # Register the global callbacks within LLDB's script interpreter
        self._register_script_callbacks()

    def _register_script_callbacks(self):
        """Registers the necessary global functions in LLDB's scripting environment."""
        self.tracer.run_cmd("script import debugger.lldb.tracer.libc_hooker")
        self.tracer.run_cmd(
            "script debugger.lldb.tracer.libc_hooker.libc_breakpoint_callback = debugger.lldb.tracer.libc_hooker.libc_breakpoint_callback"
        )
        self.tracer.run_cmd(
            "script debugger.lldb.tracer.libc_hooker.libc_return_callback = debugger.lldb.tracer.libc_hooker.libc_return_callback"
        )
        self.logger.info("Registered libc hooker callbacks in LLDB.")

    def add_async_callback(self, callback: Callable):
        """Registers a callback function to be notified of libc events."""
        if callback not in self.async_callbacks:
            self.async_callbacks.append(callback)

    def remove_async_callback(self, callback: Callable):
        """Unregisters a callback function."""
        if callback in self.async_callbacks:
            self.async_callbacks.remove(callback)

    def setup_hooks(self):
        """Sets entry breakpoints for all libc functions specified in the config."""
        libc_funcs = self.tracer.config_manager.get_libc_functions()
        if not libc_funcs:
            self.logger.info("No libc functions configured for hooking.")
            return

        self.logger.info("Setting up hooks for %d libc functions...", len(libc_funcs))
        for func_name in libc_funcs:
            bp = self.target.BreakpointCreateByName(func_name)
            if not bp.IsValid():
                self.logger.warning("Failed to set breakpoint for libc function: %s", func_name)
                continue
            # Set the global entry callback for this breakpoint
            bp.SetScriptCallbackFunction("debugger.lldb.tracer.libc_hooker.libc_breakpoint_callback")
            self.logger.info("Set entry breakpoint for %s (BP ID: %d)", func_name, bp.GetID())

    def handle_function_entry(self, frame: lldb.SBFrame):
        """Handles a hit on a libc function's entry breakpoint."""
        thread = frame.GetThread()
        thread_id = thread.GetThreadID()
        func_name = frame.GetFunctionName()

        # Get the return address (Link Register) to set a return breakpoint
        lr_value = ABI.get_lr_register(frame, self.abi_type)
        if not lr_value:
            self.logger.warning("Could not get return address for %s in thread %d.", func_name, thread_id)
            return

        # Create a one-shot breakpoint at the return address
        return_bp = self.target.BreakpointCreateByAddress(lr_value)
        if not return_bp.IsValid():
            self.logger.error("Failed to set return breakpoint for %s at LR: 0x%x", func_name, lr_value)
            return
        return_bp.SetOneShot(True)
        return_bp.SetScriptCallbackFunction("debugger.lldb.tracer.libc_hooker.libc_return_callback")

        # Push the function call context onto this thread's stack
        self.function_stacks[thread_id].append((func_name, return_bp.GetID()))

        # Log arguments and notify listeners
        args_info = self._log_function_args(frame, func_name)
        self._trigger_async_callbacks("entry", func_name, args_info, thread_id)

    def handle_function_return(self, frame: lldb.SBFrame, bp_loc: lldb.SBBreakpointLocation):
        """Handles a hit on a libc function's return breakpoint."""
        thread = frame.GetThread()
        thread_id = thread.GetThreadID()

        if thread_id not in self.function_stacks or not self.function_stacks[thread_id]:
            # This can happen if the return breakpoint is hit out of sequence
            return

        # Pop the function context from the stack
        func_name, expected_bp_id = self.function_stacks[thread_id].pop()

        # Verify that this return corresponds to the last entry
        if bp_loc.GetBreakpoint().GetID() != expected_bp_id:
            # Mismatch, something is wrong. Push it back and ignore.
            self.function_stacks[thread_id].append((func_name, expected_bp_id))
            return

        # Log return value and notify listeners
        ret_value = ABI.get_return_value(frame, self.abi_type)
        self.logger.info("<- RET %s => 0x%x", func_name, ret_value)
        self._trigger_async_callbacks("exit", func_name, ret_value, thread_id)

    def _log_function_args(self, frame: lldb.SBFrame, func_name: str) -> List[str]:
        """Parses and logs the arguments for a function call."""
        try:
            # Get raw argument register values from the ABI
            raw_args = ABI.get_function_args(frame, self.abi_type, 6)  # Get up to 6 args
            # Parse them into a human-readable format
            parsed_args = self.libc_abi.parse_args(func_name, raw_args, frame.GetThread().GetProcess())

            arg_str = ", ".join(parsed_args)
            self.logger.info("-> CALL %s(%s)", func_name, arg_str)
            return parsed_args
        except Exception as e:
            self.logger.error("Error parsing args for %s: %s", func_name, e, exc_info=True)
            return [f"<error: {e}>"]

    def _trigger_async_callbacks(self, event_type: str, func_name: str, data: Any, thread_id: int):
        """Notifies all registered listeners of a libc event."""
        event_data = {
            "type": event_type,
            "function": func_name,
            "data": data,
            "thread_id": thread_id,
        }

        # Iterate over a copy in case a callback modifies the list
        for callback in self.async_callbacks[:]:
            try:
                callback(event_data)
            except Exception as e:
                self.logger.error("Async callback %s failed: %s", callback.__name__, e, exc_info=True)
                # To prevent repeated failures, remove the faulty callback
                self.remove_async_callback(callback)
