# 2. Change to project directory
cd /Users/richard/code/terminal-llm/tools/code_completion

# 3. Initialize npm project and install dependencies
# Check if package.json exists, if not, create a basic one.
if [ ! -f package.json ]; then
  pnpm init -y
fi

# Install production dependencies
pnpm install openai

# Install development dependencies
pnpm install -D @types/vscode @types/node typescript esbuild vsce

echo "Project setup complete. You can now open this folder in VS Code."
