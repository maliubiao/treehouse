import logging
import os
import time
from typing import Callable

import lldb

from .context import TestContext
from .models import TestResult, TestStatus


class TestFunctionExecutor:
    """
    Manages the complete lifecycle of executing a single test function.
    This includes setting up the LLDB target, running the test, and cleaning up.
    """

    def __init__(self, debugger: lldb.SBDebugger, test_program: str, full_test_name: str, test_func: Callable):
        self.debugger = debugger
        self.test_program = test_program
        self.full_test_name = full_test_name
        self.test_func = test_func
        self.target: lldb.SBTarget = None
        self.process: lldb.SBProcess = None

    def run(self) -> TestResult:
        """
        Executes the test function and returns its result.
        Handles setup, execution, and teardown.
        """
        start_time = time.time()
        try:
            self._setup()
            result = self._execute_test()
        except Exception as e:
            logging.error("Test setup or execution failed for %s: %s", self.full_test_name, e, exc_info=True)
            result = TestResult(
                name=self.full_test_name,
                status=TestStatus.ERROR,
                duration=time.time() - start_time,
                message=f"Framework error: {type(e).__name__}: {str(e)}",
            )
        finally:
            self._teardown()

        if result.duration == 0:
            result.duration = time.time() - start_time
        return result

    def _setup(self):
        """Creates the target and launches the process for the test."""
        self.target = self._create_target()
        logging.info("Launching program for test: %s", self.full_test_name)
        self.process = self.target.LaunchSimple(None, None, os.getcwd())
        if not self.process or not self.process.IsValid():
            raise RuntimeError(f"Failed to launch process for {self.test_program}")

        if self.process.GetState() != lldb.eStateStopped:
            logging.warning("Process not stopped after launch. Waiting for stop...")
            context = TestContext(self.debugger, self.target, self.process)
            if not context.wait_for_stop():
                raise RuntimeError("Process did not stop at entry breakpoint")

    def _execute_test(self) -> TestResult:
        """Executes the test function within a try/except block."""
        start_time = time.time()
        result = TestResult(name=self.full_test_name, status=TestStatus.PASSED, duration=0)
        context = TestContext(debugger=self.debugger, target=self.target, process=self.process)

        try:
            self.test_func(context)
        except Exception as e:
            logging.error("Test %s failed: %s", self.full_test_name, e, exc_info=True)
            result.status = TestStatus.FAILED
            result.message = f"{type(e).__name__}: {str(e)}"

        result.duration = time.time() - start_time
        return result

    def _teardown(self):
        """Cleans up LLDB resources (process and target)."""
        if self.process and self.process.IsValid():
            if self.process.GetState() != lldb.eStateExited:
                self.process.Destroy()
        if self.target and self.target.IsValid():
            self.debugger.DeleteTarget(self.target)

    def _create_target(self) -> lldb.SBTarget:
        """Creates and configures a new LLDB target for the test."""
        target = self.debugger.CreateTarget(self.test_program)
        if not target or not target.IsValid():
            raise RuntimeError(f"Failed to create target for {self.test_program}")

        main_bp = target.BreakpointCreateByName("main", target.GetExecutable().GetFilename())
        if not main_bp or not main_bp.IsValid():
            logging.warning("Failed to set breakpoint at main. Program may not stop at entry point.")
        else:
            logging.info("Set breakpoint at main for target: %s", main_bp)

        return target
