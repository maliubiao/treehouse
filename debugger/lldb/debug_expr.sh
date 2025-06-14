python -m debugger.tracer_main --disable-html --enable-var-trace --watch-files="*/tree.py" --watch-files="*/tracer/*.py" tracer/expr_tool.py --source-comment /Users/richard/code/llvm-project/llvm/lib/Support/CommandLine.cpp

python ../../tree.py --debug-tree /Users/richard/code/llvm-project/llvm/lib/Support/CommandLine.cpp >sample.astlog

rg "$1" -C 30 sample.astlog | tail -n 200 >ast.log
rm trace.log

rg "$1" -C 30 /Users/richard/code/terminal-llm/debugger/logs/trace_report.log | head -n 300 >trace.log
