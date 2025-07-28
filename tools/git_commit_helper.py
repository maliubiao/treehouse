#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从LLM响应中提取Git提交信息并执行提交的工具。
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from colorama import Fore, Style


class GitCommitHelper:
    """
    从LLM响应中提取Git提交信息并执行提交的辅助类。
    """

    def __init__(
        self,
        response_text: Optional[str] = None,
        files_to_add: Optional[List[str]] = None,
        commit_message: Optional[str] = None,
        auto_approve: bool = False,
    ):
        """
        初始化GitCommitHelper实例。

        :param response_text: 包含提交信息的LLM响应文本。
        :param files_to_add: 要添加到暂存区的文件列表。
        :param commit_message: 直接提供的提交信息，如果提供则跳过提取。
        :param auto_approve: 是否自动批准并执行提交。
        """
        self.response_text = response_text
        self.files_to_add = files_to_add or []
        self.auto_approve = auto_approve
        self.commit_message = commit_message or self._extract_commit_message()

    def _extract_commit_message(self) -> Optional[str]:
        """
        从响应文本中提取提交信息。

        :return: 提取的提交信息，如果未找到则返回None。
        """
        if not self.response_text:
            return None

        start_marker = "[git commit message]"
        end_marker = "[end]"
        start_index = self.response_text.find(start_marker)
        if start_index == -1:
            return None

        start_index += len(start_marker)
        end_index = self.response_text.find(end_marker, start_index)
        if end_index == -1:
            return None

        # 提取并清理提交信息
        message = self.response_text[start_index:end_index].strip()
        # 将换行符标准化为\n
        message = message.replace("\r\n", "\n").replace("\r", "\n")
        return message

    def _confirm_and_edit_message(self) -> bool:
        """
        确认并允许编辑提交信息。

        :return: 如果用户确认则返回True，否则返回False。
        """
        if not self.commit_message:
            print(Fore.RED + "错误: 未找到提交信息。" + Style.RESET_ALL)
            return False

        if self.auto_approve:
            return True

        while True:
            print(Fore.CYAN + "检测到以下提交信息:" + Style.RESET_ALL)
            print(self.commit_message)
            print(Fore.CYAN + "是否继续? (y/n/e): " + Style.RESET_ALL, end="")

            try:
                choice = input().strip().lower()
            except EOFError:
                # 如果遇到EOF，视为取消
                print()  # 添加换行符以保持输出整洁
                return False

            if choice in ["y", "yes"]:
                return True
            elif choice in ["n", "no"]:
                return False
            elif choice in ["e", "edit"]:
                print(Fore.CYAN + "请输入新的提交信息 (输入'END'结束编辑):" + Style.RESET_ALL)
                lines = []
                try:
                    while True:
                        line = input()
                        if line.strip() == "END":
                            break
                        lines.append(line)
                except EOFError:
                    pass  # EOF也结束输入

                new_message = "\n".join(lines).strip()
                if not new_message:
                    print(Fore.YELLOW + "提交信息不能为空，使用原始信息。" + Style.RESET_ALL)
                else:
                    self.commit_message = new_message
                    print(Fore.GREEN + "提交信息已更新。" + Style.RESET_ALL)
                    return True
            else:
                print(Fore.YELLOW + "无效输入，请输入 'y'(是), 'n'(否), 或 'e'(编辑)。" + Style.RESET_ALL)

    def _execute_git_commands(self) -> bool:
        """
        执行Git命令来添加文件和提交。

        :return: 如果所有命令成功执行则返回True，否则返回False。
        """
        try:
            # 获取Git根目录
            git_root_result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True
            )
            git_root = Path(git_root_result.stdout.strip())

            # 如果提供了文件列表，则添加文件
            if self.files_to_add:
                # 转换为相对于Git根目录的路径
                relative_files = [str((Path.cwd() / f).relative_to(git_root)) for f in self.files_to_add]
                subprocess.run(["git", "add"] + relative_files, check=True, cwd=git_root)
            else:
                print(Fore.YELLOW + "未指定文件，跳过添加到暂存区。" + Style.RESET_ALL)
                return False

            # 执行提交
            subprocess.run(["git", "commit", "-m", self.commit_message], check=True, cwd=git_root)
            print(Fore.GREEN + f"成功提交: {self.commit_message}" + Style.RESET_ALL)
            return True

        except subprocess.CalledProcessError as e:
            print(Fore.RED + f"Git命令执行失败！\n{e.stderr}" + Style.RESET_ALL, file=sys.stderr)
            return False
        except FileNotFoundError:
            print(Fore.RED + "错误: 'git' 命令未找到。请确保Git已安装并在PATH中。" + Style.RESET_ALL, file=sys.stderr)
            return False

    def run(self) -> bool:
        """
        运行整个提交流程。

        :return: 如果提交成功则返回True，否则返回False。
        """
        # 检查是否找到了提交信息
        if not self.commit_message:
            print(Fore.RED + "在响应中未找到有效的Git提交信息。" + Style.RESET_ALL)
            return False

        # 确认并可能编辑提交信息
        if not self._confirm_and_edit_message():
            print(Fore.YELLOW + "提交已取消。" + Style.RESET_ALL)
            return False

        # 执行Git命令
        return self._execute_git_commands()


def main():
    """
    主函数，用于命令行执行。
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
        help="要添加到暂存区的文件列表。如果未提供，则跳过文件添加步骤。",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="自动批准并执行提交，无交互提示。",
    )

    args = parser.parse_args()

    if not args.response_file.exists():
        print(Fore.RED + f"错误: 响应文件未找到: {args.response_file}" + Style.RESET_ALL, file=sys.stderr)
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
        print(Fore.RED + f"发生意外错误: {e}" + Style.RESET_ALL, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
