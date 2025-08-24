#!/bin/bash
# 清理项目依赖和构建产物
echo "Cleaning project dependencies..."
rm -rf node_modules
rm -rf dist
rm -rf .vite
rm -rf .npm
rm -rf .pnpm-store

# 安装最新依赖
echo "Reinstalling dependencies..."
pnpm install --force

# 重建TypeScript类型定义
echo "Rebuilding type definitions..."
pnpm run build --force

# 启动开发服务器验证
echo "Starting development server..."
npm start
