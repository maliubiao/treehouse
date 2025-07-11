#!/bin/sh
# This script builds the VS Code extension and installs it locally.
# It's an all-in-one convenience script for developers to quickly test changes.

set -e # Exit immediately if a command exits with a non-zero status.

echo "🚀 Starting build and install process..."

# 1. Run the standard build script
# This ensures we have a fresh, clean .vsix package to install.
echo "\n[STEP 1/4] Building the extension..."
./build.sh
echo "✅ Build complete."

# 2. Find the VS Code command-line tool 'code'
echo "\n[STEP 2/4] Locating 'code' command-line tool..."
CODE_CMD=$(command -v code)
if [ -z "$CODE_CMD" ]; then
  echo "❌ Error: 'code' command not found in your PATH."
  echo "Please ensure you have installed the 'code' command."
  echo "In VS Code, open the Command Palette (Cmd+Shift+P) and run 'Shell Command: Install \\'code\\' command in PATH'."
  exit 1
fi
echo "✅ Found 'code' at: $CODE_CMD"

# 3. Determine the .vsix filename from package.json
echo "\n[STEP 3/4] Identifying VSIX package file..."
VERSION=$(node -p "require('./package.json').version")
VSIX_FILENAME="ai-code-completer-v${VERSION}.vsix"

if [ ! -f "$VSIX_FILENAME" ]; then
  echo "❌ Error: VSIX package file not found: $VSIX_FILENAME"
  echo "The build process might have failed."
  exit 1
fi
echo "✅ Found VSIX package: $VSIX_FILENAME"

# 4. Install the extension using the 'code' command
echo "\n[STEP 4/4] Installing the extension..."
"$CODE_CMD" --install-extension "$VSIX_FILENAME" --force
echo "✅ Extension installed successfully."

# Final instructions for the user
echo "\n🎉 All done! Please RELOAD your VS Code window to activate the new version."
echo "   You can do this via the Command Palette (Cmd+Shift+P) and running 'Developer: Reload Window'."
