#!/bin/sh
# This script builds the VS Code extension for production and development distribution.
# It creates a .vsix file for installation and a .tar.gz source archive.

set -e # Exit immediately if a command exits with a non-zero status.

echo "🚀 Starting build process for Treehouse Code Completer..."

# 1. Get project version from package.json
# Using Node.js is portable within a Node project environment.
VERSION=$(node -p "require('./package.json').version")
if [ -z "$VERSION" ]; then
  echo "❌ Error: Could not determine project version from package.json"
  exit 1
fi
echo "📦 Version: $VERSION"

# 2. Clean up previous build artifacts
echo "🧹 Cleaning up previous build artifacts..."
rm -rf dist/
rm -f *.vsix
rm -f *.tar.gz

# 3. Ensure dependencies are installed
echo "📦 Installing dependencies with pnpm..."
pnpm install --frozen-lockfile

# 4. Type-check the source code
echo "🧐 Type-checking source code with TypeScript..."
# This will run 'tsc --noEmit' and fail the script if there are any type errors.
pnpm run lint
echo "✅ Type-checking passed."

# 5. Compile TypeScript source code and webview assets
echo "⚙️ Compiling extension and webview..."
pnpm run compile
echo "✅ Compilation successful."

# 6. Package the extension into a .vsix file
echo "🎁 Packaging extension into a .vsix file..."
VSIX_FILENAME="treehouse-code-completer-v${VERSION}.vsix"
# Use 'pnpm exec' for robust execution of the locally installed vsce binary.
pnpm exec vsce package --no-dependencies --out "$VSIX_FILENAME"
echo "✅ Successfully created extension package: $VSIX_FILENAME"

# 7. Create a source code tarball for development
echo "📦 Creating development source tarball..."
# Check if this is a git repository before trying to use git commands.
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "⚠️  Warning: Not a git repository. Skipping source tarball creation."
else
  TAR_FILENAME="treehouse-code-completer-dev-v${VERSION}.tar.gz"
  # Use git ls-files to package only the files tracked by git, ensuring a clean archive.
  # This correctly excludes .gitignore'd files, build artifacts, etc.
  git ls-files | tar -czf "$TAR_FILENAME" -T -
  echo "✅ Successfully created source tarball: $TAR_FILENAME"
fi

echo "\n🎉 Build complete!"
