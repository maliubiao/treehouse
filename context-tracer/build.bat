@echo off
setlocal

:: This script builds the sdist and wheel packages for context-tracer.
:: It is intended for use on Windows systems.

echo "--- Cleaning up old build artifacts ---"
if exist dist\ rmdir /s /q dist
if exist build\ rmdir /s /q build
if exist src\context_tracer.egg-info\ rmdir /s /q src\context_tracer.egg-info

echo.
echo "--- Installing build dependencies ---"
pip install --upgrade build

echo.
echo "--- Building source and wheel distributions ---"
python -m build

echo.
echo "--- Build complete! ---"
echo "Packages are located in the 'dist' directory:"
dir dist

endlocal