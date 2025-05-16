# Translation Workflow Package

A parallel document translation workflow system that preserves formatting and structure.

## Features

- Parallel translation of document paragraphs
- Formatting and indentation preservation
- Translation caching
- Detailed logging and inspection
- Support for multiple translation directions

## Components

- `__main__.py`: Command-line interface
- `workflow.py`: Main workflow orchestration
- `config.py`: Configuration loading and validation
- `translation.py`: Core translation logic
- `output.py`: Output building and saving
- `logging.py`: Logging and inspection utilities

## Usage

```bash
python -m translate path/to/source.txt [path/to/config.yaml] [options]
```

### Options

- `-o/--output`: Output file path (default: <source>.translated)
- `-d/--direction`: Translation direction (zh-en or any-zh, default: zh-en)
- `-w/--workers`: Maximum parallel workers (default: 5)
- `--inspect-translate`: Display detailed translation mapping after completion

## Configuration

Create a `model.json` file with translation model settings:

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