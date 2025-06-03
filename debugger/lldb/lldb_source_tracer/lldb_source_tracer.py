#!/usr/bin/env python3
"""
LLDB Source Code Tracer
------------------------
Enhanced execution tracer with function call tracking, parameter logging,
return value capture, and call graph generation.
"""

import argparse
import hashlib
import json
import os
import re
import signal
import sys
import time
from collections import defaultdict
from datetime import datetime
from html import escape

import lldb


class SourceTracer:
    def __init__(
        self,
        target,
        args,
        output_dir="trace_output",
        log_file="trace.log",
        callgraph_file="callgraph.mmd",
        html_file="trace.html",
        json_file="trace.json",
        skip_libs=True,
        verbose=False,
    ):
        """
        Initialize the tracer with target and configuration options.

        Args:
            target (str): Path to the executable
            args (list): Command line arguments for the executable
            output_dir (str): Directory for output files
            log_file (str): Name of the log file
            callgraph_file (str): Name of the callgraph file
            html_file (str): Name of the HTML report file
            json_file (str): Name of the JSON data file
            skip_libs (bool): Skip library/internal functions
            verbose (bool): Print debug information
        """
        self.target_path = target
        self.target_args = args
        self.output_dir = output_dir
        self.log_file = os.path.join(output_dir, log_file)
        self.callgraph_file = os.path.join(output_dir, callgraph_file)
        self.html_file = os.path.join(output_dir, html_file)
        self.json_file = os.path.join(output_dir, json_file)
        self.skip_libs = skip_libs
        self.verbose = verbose

        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)

        # Initialize debugger
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(False)
        self.target = self.debugger.CreateTargetWithFileAndArch(target, lldb.LLDB_ARCH_DEFAULT)

        if not self.target:
            raise RuntimeError(f"Failed to create target for {target}")

        # Setup process and thread tracking
        self.process = None
        self.current_thread = None
        self.main_thread = None
        self.broadcaster = None  # Will be initialized after process launch

        # Execution tracking state
        self.call_stack = []
        self.function_map = {}
        self.step_counter = 0
        self.call_edges = defaultdict(lambda: defaultdict(int))
        self.log_buffer = []
        self.source_files = {}
        self.start_time = time.time()
        self.interrupted = False  # Ctrl+C interrupt flag

        # Pretty-print configuration
        self.max_depth = 3
        self.max_value_length = 200

        # Configure event handlers
        self.listener = self.debugger.GetListener()
        self.start_time = time.time()

    def start(self):
        """Launch the target process and begin tracing."""
        # Set up interrupt handler
        signal.signal(signal.SIGINT, self._handle_interrupt)

        launch_info = lldb.SBLaunchInfo(self.target_args)
        error = lldb.SBError()
        self.process = self.target.Launch(launch_info, error)

        if not self.process or error.Fail():
            raise RuntimeError(f"Failed to launch process: {error}")

        # Initialize process broadcaster after process is launched
        self.broadcaster = self.process.GetBroadcaster()
        self.broadcaster.AddListener(self.listener, lldb.SBProcess.eBroadcastBitStateChanged)

        self.main_thread = self.process.GetThreadAtIndex(0)
        self.current_thread = self.main_thread

        # Set initial breakpoint at main
        main_bp = self.target.BreakpointCreateByName("main", self.target.GetExecutable().GetFilename())
        if not main_bp.IsValid():
            raise RuntimeError("Failed to set breakpoint at main")

        print(f"Tracing started for {self.target_path}")
        print(f"Output will be saved to: {self.output_dir}")

        # Run until main is hit
        self.process.Continue()
        self._handle_stop_event()

        # Start step-by-step tracing
        self._trace_execution()

        # Generate final outputs
        self._generate_outputs()

    def _handle_interrupt(self, signum, frame):
        """Handle Ctrl+C interrupt signal."""
        print("\nReceived interrupt signal, stopping trace...")
        self.interrupted = True

        # Try to stop the process if it's still running
        if self.process and self.process.IsValid():
            self.process.Stop()

    def _trace_execution(self):
        """Main tracing loop - steps through each line of code."""
        while not self.interrupted:
            # Check process state
            state = self.process.GetState()

            if state == lldb.eStateExited:
                print(f"Process exited with status: {self.process.GetExitStatus()}")
                break
            elif state == lldb.eStateCrashed:
                print("Process crashed!")
                break
            elif state != lldb.eStateStopped:
                # Wait for process to stop or exit
                if not self._wait_for_stop(timeout=1.0):
                    if self.verbose:
                        print("Timeout waiting for process to stop")
                    continue

            self.step_counter += 1

            # Get current frame and line information
            frame = self.current_thread.GetSelectedFrame()
            line_entry = frame.GetLineEntry()

            if not line_entry.IsValid():
                if self.verbose:
                    print("Invalid line entry, stepping...")
                self._step_next()
                continue

            module = frame.GetModule()

            # Get source location
            source_file = line_entry.GetFileSpec().GetFilename()
            source_path = line_entry.GetFileSpec().GetDirectory()
            if source_path:
                full_path = os.path.join(source_path, source_file)
            else:
                full_path = source_file

            line_number = line_entry.GetLine()
            function_name = frame.GetFunctionName() or "<unknown>"

            # Cache source file content
            if full_path and os.path.exists(full_path) and full_path not in self.source_files:
                try:
                    with open(full_path, "r") as f:
                        self.source_files[full_path] = {
                            "content": f.read().splitlines(),
                            "md5": hashlib.md5(open(full_path, "rb").read()).hexdigest(),
                        }
                except Exception as e:
                    if self.verbose:
                        print(f"Warning: Failed to read source file {full_path}: {e}")

            # Skip library functions if configured
            if self.skip_libs and not self._is_user_code(module):
                self._step_over()
                continue

            # Handle function entry
            if not self.call_stack or self.call_stack[-1]["function"] != function_name:
                self._handle_function_entry(frame, function_name, source_file, line_number)

            # Log step information
            self._log_step(source_file, line_number, function_name, frame, full_path)

            # Handle function exit
            if self._is_function_exit(frame):
                self._handle_function_exit(frame)

            # Move to next line
            self._step_next()

    def _wait_for_stop(self, timeout=1.0):
        """Wait for process to stop with timeout."""
        event = lldb.SBEvent()
        if self.listener.WaitForEvent(timeout, event):
            self._handle_stop_event()
            return True
        return False

    def _handle_function_entry(self, frame, function_name, source_file, line_number):
        """Process function entry event."""
        # Get function arguments
        args = []
        arg_names = []
        for i in range(frame.GetNumberOfArguments()):
            arg = frame.GetArgumentAtIndex(i)
            if arg.IsValid():
                arg_name = arg.GetName() if arg.GetName() else f"arg{i}"
                args.append(self._pretty_print_value(arg))
                arg_names.append(arg_name)

        # Create function context
        func_ctx = {
            "function": function_name,
            "entry_line": line_number,
            "entry_file": source_file,
            "args": args,
            "arg_names": arg_names,
            "start_time": time.time(),
            "return_value": None,
            "steps": [],
        }

        # Update call stack
        self.call_stack.append(func_ctx)

        # Update call graph
        if len(self.call_stack) > 1:
            caller = self.call_stack[-2]["function"]
            self.call_edges[caller][function_name] += 1

        # Log function entry
        self._log_event("CALL", f"{function_name}({', '.join(args)})", source_file, line_number)

    def _handle_function_exit(self, frame):
        """Process function exit event."""
        if not self.call_stack:
            return

        # Get return value if available
        return_value = None
        if frame.GetFunction().GetType().GetFunctionReturnType().IsValid():
            return_value = self._get_return_value(frame)

        # Update function context
        func_ctx = self.call_stack.pop()
        func_ctx["return_value"] = return_value
        func_ctx["return_str"] = self._pretty_print_value(return_value) if return_value else "void"
        func_ctx["duration"] = time.time() - func_ctx["start_time"]

        # Store function data
        self.function_map[func_ctx["function"]] = func_ctx

        # Log function exit
        line_entry = frame.GetLineEntry()
        source_file = line_entry.GetFileSpec().GetFilename() if line_entry.IsValid() else "<unknown>"
        line_number = line_entry.GetLine() if line_entry.IsValid() else 0

        self._log_event("RETURN", f"{func_ctx['function']} -> {func_ctx['return_str']}", source_file, line_number)

    def _handle_stop_event(self):
        """Handle process stop events."""
        event = lldb.SBEvent()
        while self.listener.GetNextEvent(event):
            if event.GetType() == lldb.SBProcess.eBroadcastBitStateChanged:
                state = lldb.SBProcess.GetStateFromEvent(event)
                if state == lldb.eStateStopped:
                    self.current_thread = self.process.GetSelectedThread()
                if self.verbose:
                    state_str = {
                        lldb.eStateInvalid: "invalid",
                        lldb.eStateUnloaded: "unloaded",
                        lldb.eStateConnected: "connected",
                        lldb.eStateAttaching: "attaching",
                        lldb.eStateLaunching: "launching",
                        lldb.eStateStopped: "stopped",
                        lldb.eStateRunning: "running",
                        lldb.eStateStepping: "stepping",
                        lldb.eStateCrashed: "crashed",
                        lldb.eStateDetached: "detached",
                        lldb.eStateExited: "exited",
                        lldb.eStateSuspended: "suspended",
                    }.get(state, f"unknown ({state})")
                    print(f"Process state changed to: {state_str}")

    def _step_next(self):
        """Step to the next source line."""
        self.current_thread.StepInstruction(False)  # Step over by instruction
        self._handle_stop_event()

    def _step_over(self):
        """Step over the current line without entering functions."""
        self.current_thread.StepOver()
        self._handle_stop_event()

    def _is_function_exit(self, frame):
        """Check if we're at a function exit point."""
        if not self.call_stack:
            return False

        # Check if we're at a return instruction
        pc = frame.GetPC()
        function = frame.GetFunction()

        if not function.IsValid():
            return False

        # Check if we're at the last instruction of the function
        instructions = function.GetInstructions(self.target)
        if instructions.GetSize() == 0:
            return False

        last_instruction = instructions.GetInstructionAtIndex(instructions.GetSize() - 1)

        # Check if current PC is at function's end address
        return pc >= function.GetEndAddress().GetLoadAddress(self.target)

    def _get_return_value(self, frame):
        """Attempt to retrieve the function return value."""
        # This works for x86 and ARM architectures
        if self.target.GetTriple().startswith("x86_64"):
            return frame.FindValue("rax", lldb.eValueTypeRegister)
        elif self.target.GetTriple().startswith("arm64"):
            return frame.FindValue("x0", lldb.eValueTypeRegister)
        else:
            # Generic approach
            return frame.GetReturnValue()

    def _is_user_code(self, module):
        """Check if the module is user code."""
        if not module:
            return False

        module_path = module.GetFileSpec().GetFilename()
        return module_path and not (
            module_path.startswith("/usr/lib/") or module_path.startswith("/lib/") or module_path.startswith("/System/")
        )

    def _pretty_print_value(self, value, depth=0):
        """Recursively pretty-print SBValue objects."""
        if depth > self.max_depth:
            return "..."

        if not value or not value.IsValid():
            return "<invalid>"

        # Handle pointers
        if value.GetType().IsPointerType():
            pointee = value.Dereference()
            if pointee.IsValid():
                return f"({value.GetType().GetName()}) {self._pretty_print_value(pointee, depth + 1)}"
            else:
                return f"({value.GetType().GetName()}) 0x{value.GetValueAsUnsigned():x}"

        # Handle arrays
        if value.GetType().IsArrayType():
            elements = []
            for i in range(min(value.GetNumChildren(), 5)):  # Limit array output
                child = value.GetChildAtIndex(i)
                elements.append(self._pretty_print_value(child, depth + 1))
            return f"[{', '.join(elements)}]" + ("..." if value.GetNumChildren() > 5 else "")

        # Handle structs/classes
        if value.GetType().IsAggregateType():
            fields = []
            for i in range(min(value.GetNumChildren(), 10)):  # Limit fields output
                child = value.GetChildAtIndex(i)
                fields.append(f"{child.GetName()}={self._pretty_print_value(child, depth + 1)}")
            return f"{value.GetType().GetName()} {{{', '.join(fields)}}}" + (
                "..." if value.GetNumChildren() > 10 else ""
            )

        # Handle basic types
        summary = value.GetSummary()
        if summary:
            result = summary
        else:
            result = value.GetValue()

        # Fallback to description
        if not result:
            result = value.GetDescription()

        # Truncate long values
        if result and len(result) > self.max_value_length:
            return result[: self.max_value_length] + "..."

        return result if result else "<unknown>"

    def _log_step(self, source_file, line_number, function_name, frame, full_path):
        """Log a step event."""
        # Get local variables
        locals = []
        for var in frame.GetVariables(True, True, True, True):
            if var.IsValid():
                locals.append(
                    {"name": var.GetName(), "value": self._pretty_print_value(var), "type": var.GetTypeName()}
                )

        # Add step to current function context
        if self.call_stack:
            self.call_stack[-1]["steps"].append(
                {
                    "file": source_file,
                    "full_path": full_path,
                    "line": line_number,
                    "locals": locals,
                    "timestamp": time.time(),
                }
            )

        self._log_event("STEP", json.dumps(locals), source_file, line_number)

    def _log_event(self, event_type, message, source_file, line_number):
        """Log an event to the buffer."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_entry = {
            "timestamp": timestamp,
            "type": event_type,
            "function": self.call_stack[-1]["function"] if self.call_stack else "<unknown>",
            "source_file": source_file,
            "line": line_number,
            "message": message,
        }

        if self.verbose:
            print(f"[{timestamp}] {event_type} {source_file}:{line_number} - {message}")

        self.log_buffer.append(log_entry)

    def _generate_outputs(self):
        """Generate all output files."""
        # Generate log file
        with open(self.log_file, "w") as f:
            for entry in self.log_buffer:
                f.write(
                    f"[{entry['timestamp']}] {entry['type']} {entry['function']} "
                    f"at {entry['source_file']}:{entry['line']}\n"
                )
                f.write(f"  {entry['message']}\n\n")

        # Generate callgraph
        self._generate_callgraph()

        # Generate JSON data file
        self._generate_json_report()

        # Generate HTML report
        self._generate_html_report()

        print(f"\nTracing complete! Results saved to {self.output_dir}")
        print(f"- Execution log: {self.log_file}")
        print(f"- Call graph: {self.callgraph_file}")
        print(f"- JSON data: {self.json_file}")
        print(f"- HTML report: {self.html_file}")

    def _generate_callgraph(self):
        """Generate Mermaid call graph."""
        with open(self.callgraph_file, "w") as f:
            f.write("```mermaid\ngraph TD\n")
            for caller, callees in self.call_edges.items():
                for callee, count in callees.items():
                    f.write(f"    {caller} -->|{count}| {callee}\n")
            f.write("```\n")

    def _generate_json_report(self):
        """Generate JSON data file for frontend."""
        report_data = {
            "metadata": {
                "target": self.target_path,
                "arguments": self.target_args,
                "start_time": self.start_time,
                "end_time": time.time(),
                "step_count": self.step_counter,
                "output_dir": self.output_dir,
            },
            "log_entries": self.log_buffer,
            "functions": self.function_map,
            "call_edges": dict(self.call_edges),
            "source_files": self.source_files,
        }

        with open(self.json_file, "w") as f:
            json.dump(report_data, f, indent=2)

    def _generate_html_report(self):
        """Generate interactive HTML report."""
        with open(self.html_file, "w") as f:
            f.write("<!DOCTYPE html>\n<html>\n<head>\n")
            f.write('<meta charset="UTF-8">\n')
            f.write("<title>LLDB Source Trace Report</title>\n")
            f.write("<style>\n")
            f.write("body { font-family: monospace; margin: 20px; }\n")
            f.write(".event { margin-bottom: 15px; padding: 10px; border-left: 3px solid #ccc; }\n")
            f.write(".call { border-color: #4CAF50; background-color: #E8F5E9; }\n")
            f.write(".return { border-color: #F44336; background-color: #FFEBEE; }\n")
            f.write(".step { border-color: #2196F3; background-color: #E3F2FD; }\n")
            f.write(".timestamp { color: #757575; font-size: 0.9em; }\n")
            f.write(".function { font-weight: bold; }\n")
            f.write(".location { color: #1976D2; }\n")
            f.write(".message { margin-top: 5px; white-space: pre-wrap; }\n")
            f.write("</style>\n</head>\n<body>\n")
            f.write(f"<h1>LLDB Source Trace Report</h1>\n")
            f.write(f"<p>Target: {self.target_path}</p>\n")
            f.write(f"<p>Start time: {datetime.fromtimestamp(self.start_time)}</p>\n")
            f.write(f"<p>Duration: {time.time() - self.start_time:.3f} seconds</p>\n")
            f.write(f"<p>Steps: {self.step_counter}</p>\n")

            # Function summary table
            f.write('<h2>Function Summary</h2>\n<table border="1">\n')
            f.write("<tr><th>Function</th><th>Arguments</th><th>Return Value</th><th>Time (ms)</th></tr>\n")
            for func, ctx in self.function_map.items():
                f.write(f"<tr><td>{func}</td><td>{', '.join(ctx['args'])}</td>")
                f.write(f"<td>{self._pretty_print_value(ctx['return_value'])}</td>")
                f.write(f"<td>{ctx['duration'] * 1000:.2f}</td></tr>\n")
            f.write("</table>\n")

            # Detailed trace
            f.write("<h2>Execution Trace</h2>\n")
            for entry in self.log_buffer:
                f.write(f'<div class="event {entry["type"].lower()}">\n')
                f.write(f'<div class="timestamp">[{entry["timestamp"]}]</div>\n')
                f.write(f'<div class="location">{entry["source_file"]}:{entry["line"]}</div>\n')
                f.write(f'<div class="function">{entry["type"]} {entry["function"]}</div>\n')
                f.write(f'<div class="message">{escape(entry["message"])}</div>\n')
                f.write("</div>\n")

            # Call graph section
            f.write("<h2>Call Graph</h2>\n")
            f.write('<pre class="mermaid">\n')
            f.write("graph TD\n")
            for caller, callees in self.call_edges.items():
                for callee, count in callees.items():
                    f.write(f"    {caller} -->|{count}| {callee}\n")
            f.write("</pre>\n")

            # Add Mermaid rendering
            f.write('<script src="https://cdn.jsdelivr.net/npm/mermaid@10.0.0/dist/mermaid.min.js"></script>\n')
            f.write("<script>mermaid.initialize({startOnLoad:true});</script>\n")
            f.write("</body>\n</html>")


def main():
    parser = argparse.ArgumentParser(
        description="LLDB Source Code Tracer - Enhanced execution tracing with call graphs",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("target", help="Path to the executable")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Program arguments")
    parser.add_argument("--output-dir", default="trace_output", help="Output directory")
    parser.add_argument("--log-file", default="trace.log", help="Log file name")
    parser.add_argument("--callgraph-file", default="callgraph.mmd", help="Callgraph file name")
    parser.add_argument("--json-file", default="trace.json", help="JSON data file name")
    parser.add_argument("--html-file", default="trace.html", help="HTML report file name")
    parser.add_argument("--include-libs", action="store_true", help="Include library/internal functions in trace")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")

    args = parser.parse_args()

    tracer = SourceTracer(
        target=args.target,
        args=args.args,
        output_dir=args.output_dir,
        log_file=args.log_file,
        callgraph_file=args.callgraph_file,
        json_file=args.json_file,
        html_file=args.html_file,
        skip_libs=not args.include_libs,
        verbose=args.verbose,
    )

    try:
        tracer.start()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
