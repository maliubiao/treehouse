import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from colorama import Fore, Style

from llm_query import ModelSwitch, get_clipboard_content_string


class DocWriter:
    """
    根据大语言模型的响应，自动生成技术变更文档。
    """

    def __init__(self, model_name: str, output_dir: Path, prompt_path: Path) -> None:
        """
        初始化DocWriter。

        Args:
            model_name (str): 用于生成文档的语言模型名称。
            output_dir (Path): 保存生成文档的目录。
            prompt_path (Path): 指导文档生成的提示词文件路径。
        """
        self.model_switch: ModelSwitch = ModelSwitch()
        self.model_switch.select(model_name)
        self.output_dir: Path = output_dir
        self.prompt_path: Path = prompt_path
        self.prompt_template: str = self._load_prompt()

    def _load_prompt(self) -> str:
        """从文件加载提示词模板。"""
        try:
            return self.prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(Fore.RED + f"错误: 提示词文件未找到于 {self.prompt_path}")
            sys.exit(1)
        except Exception as e:
            print(Fore.RED + f"错误: 读取提示词文件失败: {e}")
            sys.exit(1)

    def get_git_diff(self) -> Optional[str]:
        """
        获取当前git仓库的staged变更diff。

        Returns:
            Optional[str]: diff内容，如果失败或无变更则返回None。
        """
        try:
            # 检查是否在git仓库中
            subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], check=True, capture_output=True)

            # 获取staged diff
            result = subprocess.run(
                ["git", "diff", "--cached"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            diff = result.stdout.strip()
            return diff if diff else None
        except subprocess.CalledProcessError:
            print(Fore.YELLOW + "警告: 未在git仓库中或无staged变更，无法获取diff。" + Style.RESET_ALL)
            return None
        except Exception as e:
            print(Fore.RED + f"获取git diff失败: {e}" + Style.RESET_ALL)
            return None

    def generate_doc_from_text(self, llm_response_text: str) -> str:
        """
        根据输入的LLM响应文本，生成文档内容。

        Args:
            llm_response_text (str): 包含LLM思考过程和代码变更的完整文本。

        Returns:
            str: 生成的Markdown文档内容。
        """
        if not llm_response_text.strip():
            raise ValueError("输入的LLM响应文本不能为空。")

        # 获取git diff作为额外上下文
        git_diff = self.get_git_diff()
        diff_section = f"\n\n# Git Diff 上下文（当前变更）\n\n{git_diff}" if git_diff else ""

        full_prompt = f"{self.prompt_template}\n\n---\n\n# LLM响应全文\n\n{llm_response_text}{diff_section}"

        print(Fore.CYAN + f"正在使用模型 {self.model_switch.model_name} 生成文档...")
        print(Fore.CYAN + f"输入内容长度: {len(full_prompt)} 字符" + Style.RESET_ALL)

        try:
            doc_content: str = self.model_switch.query(self.model_switch.model_name, full_prompt)
            return doc_content
        except Exception as e:
            print(Fore.RED + f"调用LLM生成文档时出错: {e}")
            return ""

    def save_doc(self, doc_content: str) -> Path:
        """
        将文档内容保存到文件。

        Args:
            doc_content (str): 要保存的Markdown文档内容。

        Returns:
            Path: 保存的文档路径。
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = self.output_dir / f"{timestamp}_doc.md"

        try:
            # 清理LLM返回中可能存在的代码块标记
            if doc_content.startswith("```markdown"):
                doc_content = doc_content[len("```markdown") :]
            if doc_content.endswith("```"):
                doc_content = doc_content[: -len("```")]
            doc_content = doc_content.strip()

            file_path.write_text(doc_content, encoding="utf-8")
            print(Fore.GREEN + f"\n文档已成功保存到: {file_path}" + Style.RESET_ALL)
            return file_path
        except Exception as e:
            print(Fore.RED + f"保存文档失败: {e}")
            sys.exit(1)


def generate_documentation_from_text(
    llm_response_text: str, output_dir: Path, model_name: str, prompt_path: Path
) -> Optional[Path]:
    """
    一个独立的API函数，用于从LLM响应文本生成文档。

    Args:
        llm_response_text (str): LLM的完整响应文本。
        output_dir (Path): 保存文档的目录。
        model_name (str): 使用的LLM名称。
        prompt_path (Path): 提示词文件路径。

    Returns:
        Optional[Path]: 成功则返回文件路径，否则返回None。
    """
    try:
        writer = DocWriter(model_name=model_name, output_dir=output_dir, prompt_path=prompt_path)
        doc_content = writer.generate_doc_from_text(llm_response_text)
        if doc_content:
            return writer.save_doc(doc_content)
    except Exception as e:
        print(Fore.RED + f"文档生成工作流执行失败: {e}")
    return None


def main() -> None:
    """CLI入口点。"""
    project_root = Path(__file__).parent.parent
    default_output_dir = project_root / "doc" / "g-docs"
    default_prompt_path = project_root / "prompts" / "doc-writer"

    parser = argparse.ArgumentParser(description="根据LLM的响应自动生成技术变更文档。")
    parser.add_argument(
        "--input-file",
        type=Path,
        default=None,
        help="包含LLM响应的输入文件路径。如果未提供，则从剪贴板读取。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output_dir,
        help=f"存放生成文档的目录 (默认: {default_output_dir})",
    )
    parser.add_argument(
        "--model",
        default="deepseek-r1",
        help="用于生成文档的语言模型 (默认: deepseek-r1)",
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        default=default_prompt_path,
        help=f"自定义的提示词文件路径 (默认: {default_prompt_path})",
    )

    args = parser.parse_args()

    llm_response_text = ""
    if args.input_file:
        try:
            print(Fore.YELLOW + f"从文件读取输入: {args.input_file}")
            llm_response_text = args.input_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(Fore.RED + f"错误: 输入文件未找到 {args.input_file}")
            sys.exit(1)
        except Exception as e:
            print(Fore.RED + f"错误: 读取输入文件失败: {e}")
            sys.exit(1)
    else:
        print(Fore.YELLOW + "未提供输入文件，尝试从剪贴板读取...")
        llm_response_text = get_clipboard_content_string()

    if not llm_response_text.strip():
        print(Fore.RED + "错误: 输入内容为空，无法生成文档。")
        print(Fore.YELLOW + "请确保文件中有内容，或剪贴板中有文本。")
        sys.exit(1)

    generate_documentation_from_text(
        llm_response_text=llm_response_text,
        output_dir=args.output_dir,
        model_name=args.model,
        prompt_path=args.prompt,
    )


if __name__ == "__main__":
    main()
