#!/usr/bin/env python
"""
一个辅助工具，用于从LLM响应中提取git commit消息，并以交互方式执行git commit。
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from colorama import Fore, Style, just_fix_windows_console

just_fix_windows_console()


class GitCommitHelper:
    """
    一个辅助类，用于从LLM响应中提取git commit消息，并处理git提交流程。
    """

    def __init__(
        self,
        response_text: Optional[str] = None,
        files_to_add: Optional[List[str]] = None,
        commit_message: Optional[str] = None,
        auto_approve: bool = False,
    ):
        """
        初始化GitCommitHelper。

        Args:
            response_text (Optional[str]): 包含git提交信息的LLM响应文本。
            files_to_add (Optional[List[str]]): 需要添加到暂存区的文件列表。
            commit_message (Optional[str]): 直接提供的提交信息，如果提供，则跳过提取步骤。
            auto_approve (bool): 是否自动批准并执行提交，跳过交互式确认。
        """
        self.response_text = response_text
        self.files_to_add = files_to_add or []
        self.auto_approve = auto_approve
        self.commit_message: Optional[str] = (
            commit_message if commit_message is not None else self._extract_commit_message()
        )

    def _extract_commit_message(self) -> Optional[str]:
        """
        从LLM响应文本中提取git commit消息。
        """
        if self.response_text is None:
            return None
        # 使用正确的正则表达式，并处理多行内容
        pattern = r"\[git commit message\]\n\[start\]\n(.*?)\n\[end\]"
        match = re.search(pattern, self.response_text, re.DOTALL)
        return match.group(1).strip() if match else None

    def _confirm_and_edit_message(self) -> bool:
        """
        向用户显示提取到的提交信息，并提供确认、编辑或取消的选项。

        Returns:
            bool: 如果用户确认（或编辑后确认）提交，则返回True。
        """
        if self.auto_approve:
            return True

        if not self.commit_message:
            print(Fore.YELLOW + "未能提取到提交信息。" + Style.RESET_ALL)
            return False

        print(Fore.CYAN + "\n提取到的提交信息:" + Style.RESET_ALL)
        print(Style.BRIGHT + self.commit_message + Style.RESET_ALL)

        while True:
            choice = (
                input(Fore.GREEN + "是否使用此提交信息？ (y/n/e) " + Style.RESET_ALL + "[y]es, [n]o, [e]dit: ")
                .lower()
                .strip()
            )

            if choice in ("y", ""):
                return True
            if choice == "n":
                return False
            if choice == "e":
                print(Fore.YELLOW + "请输入新的提交信息 (在新的一行输入 'END' 或按 Ctrl+D 结束):" + Style.RESET_ALL)
                lines = []
                try:
                    while True:
                        line = input()
                        if line == "END":
                            break
                        lines.append(line)
                except EOFError:
                    pass  # Allow Ctrl+D to finish input

                edited_message = "\n".join(lines).strip()
                if edited_message:
                    self.commit_message = edited_message
                    print(Fore.CYAN + "\n更新后的提交信息:" + Style.RESET_ALL)
                    print(Style.BRIGHT + self.commit_message + Style.RESET_ALL)
                    return True
                else:
                    print(Fore.YELLOW + "提交信息不能为空。" + Style.RESET_ALL)
                    # The loop will continue, asking y/n/e again.
            else:
                print(Fore.RED + "无效输入，请输入 'y', 'n', 或 'e'。" + Style.RESET_ALL)

    def _execute_git_commands(self) -> bool:
        """
        执行 'git add' 和 'git commit' 命令。

        Returns:
            bool: 命令成功执行返回True，否则返回False。
        """
        try:
            # 添加文件到暂存区
            if self.files_to_add:
                add_command = ["git", "add"] + self.files_to_add
                subprocess.run(add_command, check=True, capture_output=True, text=True)
                print(Fore.GREEN + f"已添加 {len(self.files_to_add)} 个文件到暂存区。" + Style.RESET_ALL)
            else:
                # 如果没有指定文件，则添加所有更改
                subprocess.run(["git", "add", "."], check=True, capture_output=True, text=True)
                print(Fore.GREEN + "已添加所有更改到暂存区。" + Style.RESET_ALL)

            # 执行提交
            if not self.commit_message:
                # This case should ideally be caught earlier, but as a safeguard:
                print(Fore.RED + "提交信息为空，无法提交。" + Style.RESET_ALL, file=sys.stderr)
                return False
            commit_command = ["git", "commit", "-m", self.commit_message]
            subprocess.run(commit_command, check=True, capture_output=True, text=True)
            print(Fore.GREEN + "代码变更已成功提交！" + Style.RESET_ALL)
            return True

        except subprocess.CalledProcessError as e:
            print(Fore.RED + "Git命令执行失败！" + Style.RESET_ALL, file=sys.stderr)
            print(f"命令: {' '.join(e.cmd)}", file=sys.stderr)
            print(f"返回码: {e.returncode}", file=sys.stderr)
            print(f"输出:\n{e.stdout}", file=sys.stderr)
            print(f"错误输出:\n{e.stderr}", file=sys.stderr)
            print(
                Fore.YELLOW + "这可能是由于 pre-commit 钩子检查失败。请检查上面的输出并手动解决问题。" + Style.RESET_ALL
            )
            return False
        except FileNotFoundError:
            print(
                Fore.RED + "错误: 'git' 命令未找到。请确保Git已安装并位于您的PATH中。" + Style.RESET_ALL,
                file=sys.stderr,
            )
            return False

    def run(self) -> bool:
        """
        执行完整的提交流程。

        Returns:
            bool: 提交流程成功完成返回True。
        """
        if not self.commit_message:
            print(Fore.YELLOW + "在响应中未找到有效的Git提交信息。" + Style.RESET_ALL)
            return False

        if self._confirm_and_edit_message():
            return self._execute_git_commands()

        print(Fore.YELLOW + "提交已取消。" + Style.RESET_ALL)
        return False


def main():
    """
    独立运行的主函数。
    """
    parser = argparse.ArgumentParser(description="从LLM响应中提取并执行Git提交。")
    parser.add_argument(
        "--response-file",
        type=Path,
        default=Path(__file__).parent.parent / ".lastgptanswer",
        help="包含LLM响应的文件的路径。",
    )
    parser.add_argument(
        "--add",
        nargs="*",
        help="要添加到暂存区的文件列表。如果未提供，则使用 'git add .'",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="自动批准并执行提交，无交互提示。",
    )
    args = parser.parse_args()

    if not args.response_file.exists():
        print(f"错误: 响应文件未找到: {args.response_file}", file=sys.stderr)
        sys.exit(1)

    try:
        response_text = args.response_file.read_text("utf-8")
        helper = GitCommitHelper(
            response_text=response_text,
            files_to_add=args.add,
            auto_approve=args.auto_approve,
        )
        if not helper.run():
            sys.exit(1)
    except Exception as e:
        print(f"发生意外错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
