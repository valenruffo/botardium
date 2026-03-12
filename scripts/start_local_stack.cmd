@echo off
setlocal

set ROOT=%~dp0..
for %%I in ("%ROOT%") do set ROOT=%%~fI

python "%ROOT%\scripts\start_local_stack.py"

endlocal
