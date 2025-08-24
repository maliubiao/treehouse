#!/bin/bash

# 测试生产构建
echo "Running build test..."
npm run build

# 检查构建产物是否存在
if [ -d "dist" ]; then
  echo "Build successful: dist directory exists"
else
  echo "Build failed: dist directory missing"
  exit 1
fi

# 测试预览服务器启动（非阻塞）
echo "Starting preview server..."
npx vite preview >/dev/null 2>&1 &
PID=$!

# 给服务器时间启动
sleep 5

# 检查服务器是否存活
if ps -p $PID >/dev/null; then
  echo "Preview server started successfully"
  kill $PID
  exit 0
else
  echo "Failed to start preview server"
  kill $PID
  exit 1
fi
