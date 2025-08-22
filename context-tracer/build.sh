#!/bin/sh
# This script builds the sdist and wheel packages for context-tracer.
# It is intended for use on macOS and Linux systems.

# Exit immediately if a command exits with a non-zero status.
set -e

echo "--- Cleaning up old build artifacts ---"
rm -rf dist/
rm -rf build/
rm -rf src/context_tracer.egg-info/
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo "\n--- Installing build dependencies ---"
# Ensure the 'build' package is installed
pip install --upgrade build

echo "\n--- Building source and wheel distributions ---"
# Run the build process
python3 -m build

echo "\n--- Build complete! ---"
echo "Packages are located in the 'dist' directory:"
ls -l dist/
