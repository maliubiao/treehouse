这是一个VS Code插件，用于查看和导航.trace格式的代码追踪日志。

## 功能特性

- 提供.trace文件语法高亮
- 支持代码追踪日志中的文件路径快速跳转
- 在右侧分屏打开目标文件并自动定位到指定行号
- 智能管理已打开的编辑器标签页
- 支持路径智能提示和行号识别

## 安装

### 安装VSCE工具
```bash
npm install -g @vscode/vsce
```

### 从VSIX安装
1. 构建VSIX包：
```bash
npm run package
```
2. 在VS Code中按 `Ctrl+Shift+P` 输入 "Install from VSIX"
3. 选择生成的 `.vsix` 文件

### 开发安装
```bash
npm install && npm run build
```
在VS Code中按 `F5` 启动调试实例

## 使用说明
1. 打开任意.trace文件
2. 点击带有下划线的文件路径（如 `/path/to/file:123`）
3. 目标文件将在右侧分屏打开并自动跳转到指定行
4. 重复点击不同路径会自动重用现有编辑器

## 开发指南

### 环境要求
- Node.js >= 16.x
- VS Code >= 1.60

### 常用命令
```bash
# 安装依赖
npm install

# 生产构建
npm run build

# 开发监视模式
npm run watch

# 生成VSIX安装包
npm run package

# 发布到市场（需要发布权限）
npm run publish
```

### 调试配置
1. 在VS Code中打开项目
2. 按 `F5` 启动调试
3. 在扩展开发宿主中：
   - 打开任意.trace文件
   - 尝试点击路径链接
   - 检查调试控制台输出

### 测试流程
1. 创建测试文件 `test.trace` 包含：
```trace
[ENTER] Sample at /path/to/testfile:1
[LEAVE] Sample at /path/to/testfile:5
```
2. 验证以下功能：
   - 语法高亮是否正确
   - 文件路径点击跳转
   - 分屏打开行为
   - 行号精确定位

## 文件格式规范
```trace
[ENTER] > 方法名 描述 at /path/to/file:行号
[LEAVE] < 方法名 at /path/to/file:行号
[CALL] 调用描述 at /path/to/file:行号
```

## 已知问题
- 不支持网络路径和特殊字符路径（计划在v0.1.1修复）
- 行号超过实际文件大小时不会提示错误（计划在v0.1.2修复）

## 贡献指南
1. Fork仓库
2. 创建特性分支 (`git checkout -b feature/your-feature`)
3. 提交修改 (`git commit -am 'Add some feature'`)
4. 推送到分支 (`git push origin feature/your-feature`)
5. 创建Pull Request