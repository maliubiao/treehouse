import time

import lldb


class TestContext:
    """Provides the debugging context for a single test function."""

    def __init__(self, debugger: lldb.SBDebugger, target: lldb.SBTarget, process: lldb.SBProcess):
        self.debugger = debugger
        self.target = target
        self.process = process

    def run_command(self, command: str) -> lldb.SBCommandReturnObject:
        """
        Executes an LLDB command.

        Args:
            command: The LLDB command string to execute.

        Returns:
            An SBCommandReturnObject with the result of the command.
        """
        ret = lldb.SBCommandReturnObject()
        self.debugger.GetCommandInterpreter().HandleCommand(command, ret)
        return ret

    def wait_for_stop(self, timeout_sec: float = 5.0) -> bool:
        """
        Waits for the process to enter the eStateStopped state.

        Args:
            timeout_sec: The maximum time to wait in seconds.

        Returns:
            True if the process stopped, False otherwise.
        """
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            state = self.process.GetState()
            if state == lldb.eStateStopped:
                return True
            time.sleep(0.1)
        return False
