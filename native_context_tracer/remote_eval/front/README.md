# Python远程调试器前端

## 功能特性

- 实时Python代码编辑器
- 执行历史记录与收藏功能
- 暗黑/明亮主题切换
- 响应式布局（适配手机、平板和桌面）
- 代码片段持久化存储
- 服务器连接状态监控

## 开发脚本

### 基本命令

```bash
# 初始化开发环境（首次克隆仓库时运行）
pnpm install

# 启动开发服务器（默认端口5173）
npm start

# 构建生产版本到 dist 目录
npm run build

# 构建并预览生产版本（先构建后启动预览服务器）
npm run dist

# 运行测试脚本（验证构建和预览功能）
bash test_commands.sh

# 完整环境重置（解决依赖问题）
bash reset_env.sh
```

### 环境重置脚本使用

```bash
# 授予执行权限
chmod +x reset_env.sh

# 运行重置脚本（会删除node_modules和缓存）
./reset_env.sh
```

## 技术栈

- React 19 + Redux Toolkit 2.8
- Material-UI 7 + Emotion 11
- Monaco Editor 4.7
- Vite 6.3
- Redux Persist 6

## 项目结构

```
front/
├── src/
│   ├── components/    # UI组件
│   ├── features/      # Redux状态切片
│   ├── hooks/         # 自定义钩子
│   ├── store.js       # Redux store配置
└── vite.config.js     # 开发服务器配置
```

## 接口代理

开发服务器代理配置：
- /evaluate -> http://localhost:5000

## 响应式布局

应用采用响应式设计：
- **大屏幕 (≥1200px)**: 代码编辑器与执行结果面板比例 9:3
- **中等屏幕 (≥900px)**: 代码编辑器与执行结果面板比例 8:4
- **小屏幕 (<900px)**: 垂直堆叠布局

## 最新更新

### 2024-06-XX: 空间利用率增强
- 移除最大宽度限制，充分利用浏览器宽度
- 编辑器高度自适应容器尺寸
- 在大屏幕上增加代码编辑器占比
- 优化操作按钮布局，减少空间浪费

### 2024-06-15: UI空间优化
- 重构代码编辑器面板布局，更充分利用空间
- 将收藏功能改为折叠式表单
- 优化操作按钮的响应式布局
- 减少不必要的边距和内边距