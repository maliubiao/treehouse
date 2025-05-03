## 一次tracer循环进程不退出的调试

```bash
python -m debugger.tracer_main tests/test_main.py --json --extract-errors
```
加了tracer不退出，挂了lldb看bt, 某个地方触发了gc
```bash
(lldb) bt
* thread #1, queue = 'com.apple.main-thread', stop reason = signal SIGSTOP
  * frame #0: 0x00000001012fbcd8 libpython3.13.dylib`gc_collect_main.llvm.14835746539171158521 + 880
    frame #1: 0x000000010142912c libpython3.13.dylib`_Py_HandlePending + 100
    frame #2: 0x0000000101391cf8 libpython3.13.dylib`_PyEval_EvalFrameDefault + 243464
    frame #3: 0x00000001015d2004 libpython3.13.dylib`method_vectorcall.llvm.5380863741279050681 + 300
    frame #4: 0x00000001012d836c libpython3.13.dylib`call_one_instrument.llvm.3817872313437876748 + 104
    frame #5: 0x00000001012d8668 libpython3.13.dylib`call_instrumentation_vector.llvm.3817872313437876748 + 384
    frame #6: 0x000000010135888c libpython3.13.dylib`_PyEval_EvalFrameDefault + 8860
    frame #7: 0x0000000101447a0c libpython3.13.dylib`PyEval_EvalCode + 132
    frame #8: 0x000000010161d5f0 libpython3.13.dylib`builtin_exec + 508
    frame #9: 0x00000001015eebd4 libpython3.13.dylib`cfunction_vectorcall_FASTCALL_KEYWORDS.llvm.17146626047067397583 + 88
    frame #10: 0x00000001013615a4 libpython3.13.dylib`_PyEval_EvalFrameDefault + 44980
    frame #11: 0x0000000101447a0c libpython3.13.dylib`PyEval_EvalCode + 132
    frame #12: 0x000000010161d5f0 libpython3.13.dylib`builtin_exec + 508
    frame #13: 0x00000001015eebd4 libpython3.13.dylib`cfunction_vectorcall_FASTCALL_KEYWORDS.llvm.17146626047067397583 + 88
    frame #14: 0x00000001013615a4 libpython3.13.dylib`_PyEval_EvalFrameDefault + 44980
    frame #15: 0x000000010153a9d8 libpython3.13.dylib`pymain_run_module + 232
    frame #16: 0x00000001014d0194 libpython3.13.dylib`Py_RunMain + 220
    frame #17: 0x00000001014c5c74 libpython3.13.dylib`pymain_main + 468
    frame #18: 0x00000001014c5a94 libpython3.13.dylib`Py_BytesMain + 36
    frame #19: 0x000000019675eb4c dyld`start + 6000
```
关闭gc gc.disable()还是没退出, 把python的 stack tracer打出来
```bash
(lldb)  expr (void)PyRun_SimpleString("import inspect; print(inspect.stack())")
[FrameInfo(frame=<frame at 0x104680640, file '<string>', line 1, code <module>>, filename='<string>', lineno=1, function='<module>', code_context=None, index=None, positions=Positions(lineno=1, end_lineno=1, col_offset=22, end_col_offset=37)), FrameInfo(frame=<frame at 0x32cbe7ae0, file '/Users/richard/code/terminal-llm/debugger/tracer.py', line 562, code _handle_exception_handled>, filename='/Users/richard/code/terminal-llm/debugger/tracer.py', lineno=562, function='_handle_exception_handled', code_context=['    def _handle_exception_handled(self, _code, _offset, exc):\n'], index=0, positions=Positions(lineno=562, end_lineno=562, col_offset=0, end_col_offset=0)), FrameInfo(frame=<frame at 0x100802680, file '/Users/richard/code/terminal-llm/tests/test_main.py', line 171, code main>, filename='/Users/richard/code/terminal-llm/tests/test_main.py', lineno=171, function='main', code_context=['    except Exception as e:\n'], index=0, positions=Positions(lineno=171, end_lineno=173, col_offset=4, end_col_offset=19)), FrameInfo(frame=<frame at 0x10061fc40, file '/Users/richard/code/terminal-llm/tests/test_main.py', line 176, code <module>>, filename='/Users/richard/code/terminal-llm/tests/test_main.py', lineno=176, function='<module>', code_context=['    main()\n'], index=0, positions=Positions(lineno=176, end_lineno=176, col_offset=4, end_col_offset=10)), FrameInfo(frame=<frame at 0x1005847b0, file '/Users/richard/code/terminal-llm/debugger/tracer_main.py', line 36, code execute_script>, filename='/Users/richard/code/terminal-llm/debugger/tracer_main.py', lineno=36, function='execute_script', code_context=['        exec(compiled_code, globals_dict)  # pylint: disable=exec-used\n'], index=0, positions=Positions(lineno=36, end_lineno=36, col_offset=8, end_col_offset=41)), FrameInfo(frame=<frame at 0x100798d50, file '/Users/richard/code/terminal-llm/debugger/tracer_main.py', line 194, code debug_main>, filename='/Users/richard/code/terminal-llm/debugger/tracer_main.py', lineno=194, function='debug_main', code_context=['            execute_script(target, args["script_args"])\n'], index=0, positions=Positions(lineno=194, end_lineno=194, col_offset=12, end_col_offset=55)), FrameInfo(frame=<frame at 0x10053cc80, file '/Users/richard/code/terminal-llm/debugger/tracer_main.py', line 231, code <module>>, filename='/Users/richard/code/terminal-llm/debugger/tracer_main.py', lineno=231, function='<module>', code_context=['    sys.exit(debug_main())\n'], index=0, positions=Positions(lineno=231, end_lineno=231, col_offset=13, end_col_offset=25)), FrameInfo(frame=<frame at 0x10463c180, file '<frozen runpy>', line 88, code _run_code>, filename='<frozen runpy>', lineno=88, function='_run_code', code_context=None, index=None, positions=Positions(lineno=88, end_lineno=88, col_offset=4, end_col_offset=27)), FrameInfo(frame=<frame at 0x103c65ad0, file '<frozen runpy>', line 198, code _run_module_as_main>, filename='<frozen runpy>', lineno=198, function='_run_module_as_main', code_context=None, index=None, positions=Positions(lineno=198, end_lineno=199, col_offset=11, end_col_offset=42))]

```
确定代码
```python

    def _handle_exception_handled(self, _code, _offset, exc):
        """Handle EXCEPTION_HANDLED event"""
        frame = sys._getframe(1)  # Get the frame where exception was handled
        if frame in self.active_frames:
            self._logic.exception_chain.pop()
            self._logic.stack_depth += 1
        return None
```
结论很明显了，在exception handler里触发了empty list exception  
改进
```python

    def _handle_exception_handled(self, _code, _offset, exc):
        """Handle EXCEPTION_HANDLED event"""
        frame = sys._getframe(1)  # Get the frame where exception was handled
        if frame in self.active_frames:
            if len(self._logic.exception_chain) > 0:
                self._logic.exception_chain.pop()
            self._logic.stack_depth += 1
        return None
```
进程顺利退出

