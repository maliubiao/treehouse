import argparse
import os
import sys
from pathlib import Path

# 假设此脚本位于项目根目录下的 'tools' 文件夹中
# 将项目根目录添加到 sys.path 以便导入 llm_query
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from llm_query import GLOBAL_PROJECT_CONFIG, extract_and_diff_files


def run_re_patch(response_file_path: Path, project_root_path: Path) -> bool:
    """
    执行从文件重新应用补丁的核心逻辑。

    Args:
        response_file_path: 包含LLM响应的文本文件路径。
        project_root_path: 项目的根目录路径。

    Returns:
        如果操作成功则返回 True，否则返回 False。
    """
    if not response_file_path.is_file():
        print(f"错误: 响应文件未找到 '{response_file_path}'", file=sys.stderr)
        return False

    if not project_root_path.is_dir():
        print(f"错误: 项目目录未找到 '{project_root_path}'", file=sys.stderr)
        return False

    # 设置全局项目配置，这对于解析相对路径至关重要
    GLOBAL_PROJECT_CONFIG.project_root_dir = str(project_root_path)

    # 切换当前工作目录到项目根目录，以确保文件操作的相对路径一致性
    os.chdir(project_root_path)

    print(f"使用项目根目录: {project_root_path}")

    try:
        content = response_file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"错误: 读取文件 '{response_file_path}' 时出错: {e}", file=sys.stderr)
        return False

    # 更新提示信息以反映交互模式
    print(f"正在从 '{response_file_path}' 以交互模式重新应用补丁...")

    # 调用核心函数，并设置 auto_apply=False 以启用交互式确认流程。
    # 这可以正确处理新文件的创建，包括其父目录。
    # save=False 因为我们是从一个已存在的文件中读取，无需再次保存响应内容。
    extract_and_diff_files(content, auto_apply=False, save=False)

    print("\n补丁应用流程已完成。")
    return True


def main():
    """
    命令行入口点。
    解析参数并调用核心逻辑。
    """
    parser = argparse.ArgumentParser(
        description="从已保存的LLM响应文件中重新应用文件修改。",
        epilog="此工具读取一个包含LLM指令（如 [overwrite whole file]）的文本文件，"
        "并以交互方式应用其中的变更。适用于恢复或重新应用补丁操作。",
    )
    parser.add_argument("response_file", type=Path, help="包含已保存LLM响应的文本文件路径。")
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="项目根目录的路径。默认为当前工作目录。",
    )
    args = parser.parse_args()

    # 解析路径为绝对路径以获得更清晰的输出
    response_file = args.response_file.resolve()
    project_dir = args.project_dir.resolve()

    if not run_re_patch(response_file, project_dir):
        sys.exit(1)


if __name__ == "__main__":
    main()
