import argparse
import base64
import os
import re
import time
import webbrowser  # 添加浏览器支持
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Tuple

from rich.console import Console
from rich.markdown import Markdown
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

import llm_query
from llm_query import ModelSwitch, perform_search

console = Console()


class KeywordExplainer:
    def __init__(self, model_name: str = "deepseek-r1", output_dir: str = "doc"):
        self.model_name = model_name
        self.model_switch = ModelSwitch()
        self.max_chunk_size = 128 * 1024  # 128K per chunk
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Check if markdown package is available for HTML generation
        self.has_markdown = False
        try:
            import markdown

            self.has_markdown = True
        except ImportError:
            console.print("[yellow]注意: 未安装'markdown'包，跳过HTML生成。请安装：pip install markdown[/yellow]")

    def _chunk_search_results(self, search_results: dict) -> List[dict]:
        """将搜索结果分块，每块不超过最大上下文大小"""
        chunks = []
        current_chunk = {"symbols": [], "size": 0}

        for symbol in search_results.values():
            symbol_size = len(symbol["code"].encode("utf-8"))

            # 符号太大需要单独处理
            if symbol_size > self.max_chunk_size * 0.8:
                console.print(f"[yellow]警告: 符号 '{symbol['name']}' 过大 ({symbol_size} bytes)，将单独处理[/yellow]")
                if current_chunk["symbols"]:
                    chunks.append(current_chunk)
                    current_chunk = {"symbols": [], "size": 0}
                chunks.append({"symbols": [symbol], "size": symbol_size})
                continue

            # 添加到当前块
            if current_chunk["size"] + symbol_size > self.max_chunk_size:
                chunks.append(current_chunk)
                current_chunk = {"symbols": [], "size": 0}

            current_chunk["symbols"].append(symbol)
            current_chunk["size"] += symbol_size

        if current_chunk["symbols"]:
            chunks.append(current_chunk)

        return chunks

    def _generate_prompt(self, symbols: List[dict]) -> str:
        """为符号块生成提示词"""
        prompt_header = """
# 代码概念解释任务

请根据提供的代码片段解释以下概念：
1. 每个符号的功能和用途
2. 在项目中的上下文作用
3. 设计原理和实现细节
4. 逻辑推理和假设场景（包括给出假设输入与输出）
5. 常见使用错误示例（举例说明）
6. 调试线索（用户如何一步步到达此代码）

请用专业但易懂的语言解释，并确保：
- 包含必要的代码引用（使用 ``` 标记代码块）
- 解释技术术语
- 解析概念与概念之间的联系，以及一串外部命令或者写一小段程序作为核实方式
- 说明可能的常见使用错误
- 生成必要的术语表，以及写一个代码块作为术语关系的核实方式
- 以中文回复

代码片段：
"""
        code_snippets = []
        for symbol in symbols:
            file_ext = Path(symbol["file_path"]).suffix.lstrip(".") or "text"
            code_snippets.append(f"## {symbol['name']} ({symbol['file_path']})")
            code_snippets.append(f"```{file_ext}")
            code_snippets.append(symbol["code"])
            code_snippets.append("```")

        return prompt_header + "\n".join(code_snippets)

    def _query_model(self, prompt: str, chunk_index: int, total_chunks: int) -> Tuple[int, str]:
        """查询模型并处理响应，返回块索引和结果"""
        try:
            console.print(f"[cyan]处理块 {chunk_index + 1}/{total_chunks} (大小: {len(prompt)} 字符)[/cyan]")
            result = self.model_switch.query(self.model_name, prompt, stream=True)
            return chunk_index, result
        except (ConnectionError, TimeoutError) as e:
            console.print(f"[red]查询块 {chunk_index} 时出错: {str(e)}[/red]")
            return chunk_index, f"## 查询错误\n```\n{str(e)}\n```"

    def _sanitize_filename(self, name: str) -> str:
        """移除文件名中的特殊字符"""
        return re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_")

    def _generate_html(self, md_file: Path, output_html: Path) -> None:
        """将Markdown文件转换为带tab切换和可折叠侧边栏的HTML"""
        try:
            # 读取Markdown内容
            with open(md_file, "r", encoding="utf-8") as f:
                md_content = f.read()
                base64_content = base64.b64encode(md_content.encode("utf-8")).decode("ascii")

            # 基本HTML结构
            html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>关键词解释: {md_file.stem}</title>
    <style>
        body{{
            font-family: sans-serif;
            margin: 0;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }}
        header{{
            padding: 20px;
            background: #f5f5f5;
            border-bottom: 1px solid #ddd;
            position: relative;
        }}
        #main-container{{
            display: flex;
            flex: 1;
            overflow: hidden;
        }}
        #sidebar{{
            width: 250px;
            background: #f8f8f8;
            border-right: 1px solid #ddd;
            overflow-y: auto;
            transition: all 0.3s ease;
        }}
        #sidebar.collapsed{{
            width: 40px;
        }}
        #sidebar-toggle{{
            position: absolute;
            top: 10px;
            right: 10px;
            background: none;
            border: none;
            font-size: 20px;
            cursor: pointer;
            z-index: 10;
        }}
        #symbol-list{{
            padding: 10px;
            padding-top: 40px;
        }}
        .symbol-item{{
            padding: 8px 12px;
            margin-bottom: 5px;
            border-radius: 4px;
            cursor: pointer;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .symbol-item:hover{{
            background: #e9e9e9;
        }}
        .symbol-item.active{{
            background: #e0e0e0;
            font-weight: bold;
        }}
        #content-area{{
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}
        #tab-buttons{{
            padding: 10px 20px;
            background: #f5f5f5;
            border-bottom: 1px solid #ddd;
            display: flex;
            flex-wrap: nowrap;
            overflow-x: auto;
            overflow-y: hidden;
            height: 50px;
            align-items: center;
            gap: 5px;
        }}
        .tab-button{{
            padding: 8px 16px;
            background: #eee;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            white-space: nowrap;
            flex-shrink: 0;
        }}
        .tab-button.active{{
            background: #ddd;
            font-weight: bold;
        }}
        #tab-contents{{
            flex: 1;
            padding: 20px;
            overflow-y: auto;
        }}
        .tab-content{{
            display: none;
        }}
        .tab-content.active{{
            display: block;
        }}
        pre{{
            background-color: #f5f5f5;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }}
        code{{
            font-family: monospace;
        }}
        .highlight{{
            background-color: #f5f5f5;
            padding: 10px;
            border-radius: 5px;
        }}
    </style>
</head>
<body>
    <header>
        <h1>关键词解释: {md_file.stem}</h1>
        <button id="sidebar-toggle">☰</button>
    </header>
    
    <div id="main-container">
        <div id="sidebar">
            <div id="symbol-list"></div>
        </div>
        
        <div id="content-area">
            <div id="tab-buttons"></div>
            <div id="tab-contents"></div>
        </div>
    </div>
    
    <!-- 嵌入Markdown内容 -->
    <script>
       function base64Decode(str){{
       try{{
           const binString = atob(str);
           const bytes = new Uint8Array(binString.length);
           for(let i=0;i<binString.length;i++){{
               bytes[i] = binString.charCodeAt(i);
           }}
           return new TextDecoder('utf-8').decode(bytes);
       }}catch(e){{
           console.error('Base64解码失败:',e);
           return '';
       }}
       }}
        const base64Content = "{base64_content}";
        const mdContent = base64Decode(base64Content);
    </script>
    
    <!-- 添加markdown解析器 -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    
    <script>
        document.addEventListener('DOMContentLoaded',function(){{
            const sidebar = document.getElementById('sidebar');
            const sidebarToggle = document.getElementById('sidebar-toggle');
            
            const sidebarCollapsed = localStorage.getItem('sidebarCollapsed')==='true';
            if(sidebarCollapsed){{
                sidebar.classList.add('collapsed');
            }}
            
            sidebarToggle.addEventListener('click',function(e){{
                e.stopPropagation();
                sidebar.classList.toggle('collapsed');
                localStorage.setItem('sidebarCollapsed',sidebar.classList.contains('collapsed'));
            }});
            
            try{{
                const htmlContent = marked.parse(mdContent);
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = htmlContent;
                const headers = tempDiv.querySelectorAll('h2');
                
                if(headers.length===0){{
                    const errorDiv = document.createElement('div');
                    errorDiv.className = 'error-message';
                    errorDiv.textContent = '未找到有效内容标题';
                    document.getElementById('content-area').appendChild(errorDiv);
                    return;
                }}
                
                const tabButtons = document.getElementById('tab-buttons');
                const tabContents = document.getElementById('tab-contents');
                const symbolList = document.getElementById('symbol-list');
                
                headers.forEach((header,index)=>{{
                    const button = document.createElement('button');
                    button.className = 'tab-button';
                    button.textContent = header.textContent;
                    button.dataset.index = index;
                    tabButtons.appendChild(button);
                    
                    const symbolItem = document.createElement('div');
                    symbolItem.className = 'symbol-item';
                    symbolItem.dataset.index = index;

                    const match = header.textContent.match(/^(.+?) \((.+)\)$/);
                    if(match){{
                        const symbolName = match[1];
                        const filePath = match[2];
                        const fileName = filePath.split('/').pop();
                        symbolItem.textContent = `${{fileName}}: ${{symbolName}}`;
                    }}else{{
                        symbolItem.textContent = header.textContent;
                    }}
                    symbolList.appendChild(symbolItem);
                    
                    const contentDiv = document.createElement('div');
                    contentDiv.className = 'tab-content';
                    contentDiv.id = `content-${{index}}`;
                    
                    let nextElement = header.nextElementSibling;
                    while(nextElement&&nextElement.tagName!=='H2'){{
                        contentDiv.appendChild(nextElement.cloneNode(true));
                        nextElement = nextElement.nextElementSibling;
                    }}
                    
                    tabContents.appendChild(contentDiv);
                    
                    button.addEventListener('click',function(){{
                        document.querySelectorAll('.tab-button').forEach(btn=>{{
                            btn.classList.remove('active');
                        }});
                        document.querySelectorAll('.tab-content').forEach(content=>{{
                            content.classList.remove('active');
                        }});
                        document.querySelectorAll('.symbol-item').forEach(item=>{{
                            item.classList.remove('active');
                        }});
                        
                        this.classList.add('active');
                        contentDiv.classList.add('active');
                        symbolItem.classList.add('active');
                        localStorage.setItem('activeTab',index);
                        
                        setTimeout(()=>{{
                            document.querySelectorAll('pre code').forEach((block)=>{{
                                hljs.highlightElement(block);
                            }});
                        }},100);
                    }});
                    
                    symbolItem.addEventListener('click',function(){{
                        button.click();
                    }});
                }});
                
                const activeTabIndex = localStorage.getItem('activeTab');
                if(activeTabIndex!==null&&headers[activeTabIndex]){{
                    document.querySelector(`.tab-button[data-index="${{activeTabIndex}}"]`).click();
                }}else if(headers.length>0){{
                    document.querySelector('.tab-button').click();
                }}
                
                setTimeout(()=>{{
                    document.querySelectorAll('pre code').forEach((block)=>{{
                        hljs.highlightElement(block);
                    }});
                }},500);
                
            }}catch(e){{
                const errorDiv = document.createElement('div');
                errorDiv.className = 'error-message';
                errorDiv.textContent = '渲染内容时出错: '+e.message;
                document.getElementById('content-area').appendChild(errorDiv);
                console.error(e);
            }}
        }});
    </script>
    
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.7.0/styles/github.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.7.0/highlight.min.js"></script>
    <script>hljs.highlightAll();</script>
</body>
</html>
            """

            with open(output_html, "w", encoding="utf-8") as f:
                f.write(html_content)
            return output_html  # 返回生成的HTML文件路径

        except (IOError, OSError) as e:
            console.print(f"[red]生成HTML时出错: {str(e)}[/red]")
            return None

    def explain_keywords(self, keywords: List[str], file_list: List[str] = None) -> Optional[Path]:
        """主函数：执行关键词解释流程"""
        if not keywords or any(not k.strip() for k in keywords):
            raise ValueError("需要至少一个有效搜索关键词")

        with console.status("[bold green]搜索代码库...[/bold green]", spinner="dots"):
            search_results = perform_search(
                keywords,
                os.path.join(llm_query.GLOBAL_PROJECT_CONFIG.project_root_dir, llm_query.LLM_PROJECT_CONFIG),
                max_context_size=llm_query.GLOBAL_MODEL_CONFIG.max_context_size,
                file_list=file_list,
            )

        if not search_results:
            console.print("[yellow]未找到匹配的符号[/yellow]")
            return None

        console.print(f"[green]找到 {len(search_results)} 个相关符号[/green]")

        chunks = self._chunk_search_results(search_results)
        console.print(f"[green]将结果分成 {len(chunks)} 个处理块[/green]")

        safe_keywords = [self._sanitize_filename(k) for k in keywords]
        base_name = f"keyword-{'-'.join(safe_keywords)}"
        output_md = self.output_dir / f"{base_name}.md"

        prompts = [self._generate_prompt(chunk["symbols"]) for chunk in chunks]

        results = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("解释代码概念...", total=len(chunks))

            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = []
                for i, _ in enumerate(chunks):
                    futures.append(executor.submit(self._query_model, prompts[i], i, len(chunks)))

                for future in as_completed(futures):
                    results.append(future.result())
                    progress.update(task, advance=1)

        results.sort(key=lambda x: x[0])

        with open(output_md, "w", encoding="utf-8") as f:
            f.write(f"# 关键词解释: {', '.join(keywords)}\n\n")
            f.write("## 解释结果\n\n")
            for chunk_index, result in results:
                f.write(f"### Part {chunk_index + 1}\n\n")
                f.write(result)
                f.write("\n\n")

            f.write("## 附录: 原始提示词\n\n")
            f.write("以下是发送给大模型的原始提示词，供参考:\n\n")
            for i, prompt in enumerate(prompts):
                f.write(f"### Part {i + 1} Prompt\n\n")
                f.write(f"```text\n{prompt}\n```\n\n")

            f.write(f"---\n*生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}*\n")

        console.print(f"[bold green]结果已保存至: {output_md}[/bold green]")

        output_html = None
        if self.has_markdown:
            output_html = self.output_dir / f"{base_name}.html"
            html_file = self._generate_html(output_md, output_html)
            if html_file:
                console.print(f"[bold green]HTML版本已生成: {output_html}[/bold green]")
                console.print(
                    Markdown(
                        f"# 关键词解释完成\n"
                        f"- 查看Markdown结果: [file://{output_md.absolute()}](file://{output_md.absolute()})\n"
                        f"- 查看HTML版本(带tab切换): [file://{output_html.absolute()}](file://{output_html.absolute()})"
                    )
                )
            else:
                output_html = None
        else:
            console.print(
                Markdown(
                    f"# 关键词解释完成\n查看完整结果: [file://{output_md.absolute()}](file://{output_md.absolute()})"
                )
            )

        return output_html  # 返回HTML文件路径用于自动打开


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="代码关键词搜索解释工具", formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("keywords", nargs="+", help="要搜索的关键词列表")
    parser.add_argument("-f", "--file-list", type=str, help="包含要搜索的文件路径列表的文件（每行一个路径）")
    parser.add_argument("-m", "--model", type=str, default="deepseek-r1", help="使用的LLM模型名称")
    parser.add_argument(
        "-o", "--output-dir", type=str, default=None, help="输出目录路径（默认使用$GPT_PATH/obsidian/keyword_search）"
    )
    parser.add_argument("--clean", action="store_true", help="清理所有之前的搜索结果文件")
    return parser.parse_args()


def read_file_list(file_path: str) -> List[str]:
    """从文件中读取文件路径列表"""
    if not file_path:
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except (FileNotFoundError, PermissionError, UnicodeDecodeError) as e:
        console.print(f"[red]读取文件列表错误: {str(e)}[/red]")
        return None


def get_default_output_dir() -> Path:
    """获取默认输出目录"""
    # 尝试从环境变量获取GPT_PATH
    gpt_path = os.environ.get("GPT_PATH")
    if gpt_path:
        default_dir = Path(gpt_path) / "obsidian" / "keyword_search"
    else:
        default_dir = Path("doc")

    # 确保目录存在
    default_dir.mkdir(parents=True, exist_ok=True)
    return default_dir


def main():
    args = parse_arguments()

    # 确定输出目录
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = get_default_output_dir()

    # 清理旧结果（如果指定）
    if args.clean:
        if output_dir.exists():
            for file in output_dir.glob("keyword-*.md"):
                file.unlink()
                console.print(f"[yellow]已删除旧结果文件: {file}[/yellow]")
            for file in output_dir.glob("keyword-*.html"):
                if file.exists():
                    file.unlink()
                    console.print(f"[yellow]已删除旧HTML文件: {file}[/yellow]")
            for file in output_dir.glob("keyword-*.json"):
                if file.exists():
                    file.unlink()
                    console.print(f"[yellow]已删除旧JSON文件: {file}[/yellow]")
            console.print(f"[green]清理完成: {output_dir}[/green]")
        else:
            console.print(f"[yellow]输出目录不存在: {output_dir}[/yellow]")
        return

    # 读取文件列表
    file_list = read_file_list(args.file_list) if args.file_list else None
    ModelSwitch().select(args.model)

    # 执行解释
    explainer = KeywordExplainer(model_name=args.model, output_dir=str(output_dir))
    try:
        html_path = explainer.explain_keywords(args.keywords, file_list)

        # 自动打开浏览器
        if html_path and html_path.exists():
            console.print(f"[bold green]正在浏览器中打开结果...[/bold green]")
            try:
                webbrowser.open(f"file://{html_path.absolute()}")
            except Exception as e:
                console.print(f"[yellow]无法打开浏览器: {str(e)}[/yellow]")
                console.print(f"请手动打开文件: file://{html_path.absolute()}")
    except (FileNotFoundError, PermissionError) as e:
        console.print(f"[bold red]文件操作错误: {str(e)}[/bold red]")
    except RuntimeError as e:
        console.print(f"[bold red]运行时错误: {str(e)}[/bold red]")
    except Exception as e:
        console.print(f"[bold red]未处理的错误: {str(e)}[/bold red]")
        raise  # 重新抛出未知异常


if __name__ == "__main__":
    main()
