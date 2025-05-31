# LLDB Tracer

高级LLDB调试工具，提供增强的调试功能和可视化界面。

## 新架构说明

项目已重构为模块化结构：

```
tracer/
├── __init__.py         # 包入口
├── core.py             # Tracer核心类
├── config.py           # 配置管理
├── logging.py          # 日志管理
├── symbols.py          # 符号处理和渲染
├── utils.py            # 工具函数
├── events.py           # 事件处理
└── breakpoints.py      # 断点相关
tracer_main.py          # 主入口脚本
```

## 安装

```bash
pip install -r requirements.txt
```

## 使用示例

基本使用：
```bash
./tracer_main.py -e /path/to/program -a arg1 -a arg2
```

启用详细日志：
```bash
./tracer_main.py -e /path/to/program --verbose
```

生成跳过模块配置：
```bash
./tracer_main.py -e /path/to/program --dump-modules-for-skip
```

## 新功能

### 环境变量配置
在配置文件中设置环境变量：
```yaml
# tracer_config.yaml
environment:
  DEBUG: "1"
  PATH: "/custom/path:$PATH"
  CUSTOM_SETTING: "special_value"
```

### 模块跳过配置
使用`--dump-modules-for-skip`生成配置，工具会交互式显示所有模块并让用户选择保留的模块，其余模块将被跳过。

### 符号可视化
运行后会生成`symbols.html`文件，在浏览器中打开可查看交互式符号信息。

## 测试

运行测试脚本：
```bash
./test_tracer.sh
```

测试环境变量功能：
```bash
./test_env_vars.sh
```