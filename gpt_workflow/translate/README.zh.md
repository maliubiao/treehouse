

# 翻译工作流套件


一个保留格式与结构的并行文档翻译工作流系统。

## 功能特性


- 文档段落的并行翻译  
- 格式与缩进保留  
- 翻译缓存机制  
- 详尽的日志记录与审查  
- 支持多语种互译方向


## 组件说明

- `__main__.py`: 命令行接口
- `workflow.py`: 主工作流编排
- `config.py`: 配置加载与验证
- `translation.py`: 核心翻译逻辑
- `output.py`: 输出构建与保存

- `logging.py`: 日志记录与检查工具集



## 用法

```bash
python -m translate path/to/source.txt [path/to/config.yaml] [options]

```


### 选项


- `-o/--output`: 输出文件路径（默认：<源文件>.translated）
- `-d/--direction`: 翻译方向（zh-en 或 any-zh，默认：zh-en）
- `-w/--workers`: 最大并行工作线程数（默认：5）
- `--inspect-translate`: 完成后显示详细翻译对照表


## 配置


创建包含翻译模型设置的 `model.json` 文件：

```json
    {
        "translate": {
        "key": "your-api-key",
        "base_url": "https://api.example.com/v1",
        "model_name": "your-model",
        "max_context_size": 131072,
        "max_tokens": 8096,
        "is_thinking": false,
    "temperature": 0.6
}
}
```