#!/usr/bin/env python3
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

try:
    import yaml
except ImportError:
    print("错误: PyYAML库未安装。请运行 'pip install pyyaml' 进行安装。", file=sys.stderr)
    sys.exit(1)

try:
    from colorama import Fore, Style, init
except ImportError:
    print(
        "提示: colorama库未安装。输出将不带颜色。可以运行 'pip install colorama' 来安装。",
        file=sys.stderr,
    )

    # 如果没有colorama，提供一个无操作的替代品
    class Fore:
        GREEN = RED = YELLOW = CYAN = MAGENTA = WHITE = ""

    class Style:
        BRIGHT = RESET_ALL = ""


# --- 常量 ---
BAR_CHAR = "█"
MAX_BAR_WIDTH = 50
USD_TO_CNY_RATE = 7.0  # 近似汇率


# --- 辅助函数 ---
def pad_cjk(text: str, width: int) -> str:
    """
    将字符串填充到指定的显示宽度（左对齐），正确处理CJK字符。
    假定一个CJK字符在终端中占据两个单元格宽度。
    """
    # 基于Unicode范围的简化检查来计算CJK字符的显示宽度
    display_width = sum(2 if "\u4e00" <= char <= "\u9fff" else 1 for char in text)
    padding = width - display_width
    return text + " " * (padding if padding > 0 else 0)


def format_tokens(n: int) -> str:
    """将大量的Token计数格式化为人类可读的字符串 (k, M)。"""
    if n is None:
        n = 0
    if abs(n) < 1000:
        return str(n)
    if abs(n) < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.2f}M"


def print_header(title: str):
    """打印带样式的标题。"""
    line = "=" * (len(title) + 4)
    print("\n" + Fore.MAGENTA + Style.BRIGHT + line)
    print(f"| {title} |")
    print(line + Style.RESET_ALL)


class UsageAnalyzer:
    """
    从 .model_usage.yaml 文件分析并展示LLM API的使用情况。
    """

    def __init__(self, usage_file_path: str):
        """
        初始化分析器。

        参数:
            usage_file_path (str): .model_usage.yaml 文件的路径。
        """
        self.usage_file_path = usage_file_path
        self.data = self._load_data()

    def _load_data(self) -> dict:
        """加载并解析YAML格式的消费记录文件。"""
        if not os.path.exists(self.usage_file_path):
            print(Fore.RED + f"错误: 消费记录文件未找到 '{self.usage_file_path}'")
            print(Fore.YELLOW + "请先运行LLM查询脚本以生成消费数据。")
            sys.exit(1)
        try:
            with open(self.usage_file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data or {}
        except yaml.YAMLError as e:
            print(Fore.RED + f"错误: 无法解析YAML文件: {e}")
            sys.exit(1)
        except Exception as e:
            print(Fore.RED + f"错误: 读取消费记录文件失败: {e}")
            sys.exit(1)

    def _get_data_for_period(self, days: int) -> list[tuple[datetime.date, dict]]:
        """筛选出最近N天的数据并排序。"""
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days - 1)

        filtered_data = []
        for date_str, daily_data in self.data.items():
            try:
                current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if start_date <= current_date <= end_date:
                    filtered_data.append((current_date, daily_data))
            except (ValueError, TypeError):
                # 忽略格式错误的日期键
                continue

        # 按日期降序排序 (最近的在前)
        return sorted(filtered_data, key=lambda item: item[0], reverse=True)

    def display_report(self, days: int):
        """
        生成并打印指定时间段的完整消费报告。

        参数:
            days (int): 报告包含的最近天数。
        """
        period_data = self._get_data_for_period(days)

        if not period_data:
            print(Fore.YELLOW + f"在最近 {days} 天内未找到任何消费数据。")
            return

        start_date = (datetime.now().date() - timedelta(days=days - 1)).isoformat()
        end_date = datetime.now().date().isoformat()

        print_header(f"LLM API 消费报告 (最近 {days} 天)")
        print(f"查询时段: {Fore.CYAN}{start_date}{Style.RESET_ALL} 至 {Fore.CYAN}{end_date}{Style.RESET_ALL}")

        self._display_summary(period_data)
        self._display_daily_table(period_data)
        self._display_cost_chart(period_data)
        self._display_model_breakdown(period_data)

    def _display_summary(self, period_data: list):
        """计算并展示时间段内的总体摘要。"""
        total_cost = 0.0
        total_calls = 0
        total_input_tokens = 0
        total_output_tokens = 0

        for _, data in period_data:
            total_cost += data.get("total_cost", 0)
            total_input_tokens += data.get("total_input_tokens", 0)
            total_output_tokens += data.get("total_output_tokens", 0)
            for model_data in data.get("models", {}).values():
                total_calls += model_data.get("count", 0)

        cost_cny = total_cost * USD_TO_CNY_RATE

        print_header("时段总览")
        print(
            f"  - {Fore.WHITE}总消费:{Style.RESET_ALL}  {Fore.GREEN}${total_cost:.4f}{Style.RESET_ALL} (约 ¥{cost_cny:.2f})"
        )
        print(f"  - {Fore.WHITE}总调用:{Style.RESET_ALL} {Fore.CYAN}{total_calls}{Style.RESET_ALL} 次")
        print(
            f"  - {Fore.WHITE}总输入:{Style.RESET_ALL}  {Fore.CYAN}{format_tokens(total_input_tokens)}{Style.RESET_ALL} Tokens"
        )
        print(
            f"  - {Fore.WHITE}总输出:{Style.RESET_ALL} {Fore.CYAN}{format_tokens(total_output_tokens)}{Style.RESET_ALL} Tokens"
        )

    def _display_daily_table(self, period_data: list):
        """展示每日消费明细的表格。"""
        print_header("每日明细")

        # 定义列的显示宽度以保证对齐
        W = {"date": 12, "cost": 12, "calls": 10, "in": 14, "out": 14}

        # 使用 pad_cjk 函数创建表头以处理中文字符
        header = (
            f"| {pad_cjk('日期', W['date'])} "
            f"| {pad_cjk('消费 ($)', W['cost'])} "
            f"| {pad_cjk('调用次数', W['calls'])} "
            f"| {pad_cjk('输入Token', W['in'])} "
            f"| {pad_cjk('输出Token', W['out'])} |"
        )

        # 根据列的视觉宽度计算分隔线长度
        separator_len = sum(W.values()) + (len(W) * 3) + 1

        print(Fore.YELLOW + header)
        print(Fore.YELLOW + "-" * separator_len)

        for date, data in period_data:
            cost = data.get("total_cost", 0)
            input_tokens = data.get("total_input_tokens", 0)
            output_tokens = data.get("total_output_tokens", 0)
            calls = sum(m.get("count", 0) for m in data.get("models", {}).values())

            # 数据行使用标准格式化，宽度与表头一致
            row = (
                f"| {str(date):<{W['date']}} "
                f"| {f'${cost:.4f}':<{W['cost']}} "
                f"| {str(calls):<{W['calls']}} "
                f"| {format_tokens(input_tokens):<{W['in']}} "
                f"| {format_tokens(output_tokens):<{W['out']}} |"
            )
            print(row)
        print(Fore.YELLOW + "-" * separator_len)

    def _display_cost_chart(self, period_data: list):
        """展示每日消费的水平条形图。"""
        print_header("每日消费图表")

        costs = [d.get("total_cost", 0) for _, d in period_data]
        max_cost = max(costs) if costs else 0

        if max_cost == 0:
            print("没有消费数据可供制图。")
            return

        for date, data in reversed(period_data):  # 图表从最早的日期开始显示
            cost = data.get("total_cost", 0)
            bar_len = int((cost / max_cost) * MAX_BAR_WIDTH) if max_cost > 0 else 0
            bar = BAR_CHAR * bar_len
            print(f"{str(date)} | {Fore.GREEN}${cost:<7.4f}{Style.RESET_ALL} | {Fore.CYAN}{bar}{Style.RESET_ALL}")

    def _display_model_breakdown(self, period_data: list):
        """按模型分类展示消费统计。"""
        model_summary = defaultdict(lambda: {"cost": 0.0, "count": 0, "input_tokens": 0, "output_tokens": 0})

        for _, data in period_data:
            for model_name, model_data in data.get("models", {}).items():
                model_summary[model_name]["cost"] += model_data.get("cost", 0)
                model_summary[model_name]["count"] += model_data.get("count", 0)
                model_summary[model_name]["input_tokens"] += model_data.get("input_tokens", 0)
                model_summary[model_name]["output_tokens"] += model_data.get("output_tokens", 0)

        if not model_summary:
            return

        print_header("模型消费排行")

        # 动态计算模型名称列的宽度，同时确保宽度不小于表头“模型”的宽度
        model_header_display_width = 4  # '模型' 的显示宽度
        max_model_name_len = max([len(name) for name in model_summary.keys()] + [model_header_display_width])

        # 定义列的显示宽度
        W = {
            "model": max_model_name_len,
            "cost": 12,
            "calls": 10,
            "in": 14,
            "out": 14,
        }

        # 使用 pad_cjk 函数创建表头
        header = (
            f"| {pad_cjk('模型', W['model'])} "
            f"| {pad_cjk('消费 ($)', W['cost'])} "
            f"| {pad_cjk('调用次数', W['calls'])} "
            f"| {pad_cjk('输入Token', W['in'])} "
            f"| {pad_cjk('输出Token', W['out'])} |"
        )
        separator_len = sum(W.values()) + (len(W) * 3) + 1

        print(Fore.YELLOW + header)
        print(Fore.YELLOW + "-" * separator_len)

        # 按消费降序排序
        sorted_models = sorted(model_summary.items(), key=lambda item: item[1]["cost"], reverse=True)

        for model_name, summary in sorted_models:
            cost = summary["cost"]
            count = summary["count"]
            in_tokens = summary["input_tokens"]
            out_tokens = summary["output_tokens"]
            row = (
                f"| {model_name:<{W['model']}} "
                f"| {f'${cost:.4f}':<{W['cost']}} "
                f"| {count:<{W['calls']}} "
                f"| {format_tokens(in_tokens):<{W['in']}} "
                f"| {format_tokens(out_tokens):<{W['out']}} |"
            )
            print(row)
        print(Fore.YELLOW + "-" * separator_len)


def main():
    """脚本的主入口点。"""
    # 脚本在 tools/ 目录下, .model_usage.yaml 在其父目录
    default_usage_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".model_usage.yaml"))

    parser = argparse.ArgumentParser(
        description="分析并展示 LLM API 的消费情况。",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("-d", "--days", type=int, default=7, help="报告要包含的最近天数 (默认: 7)。")
    parser.add_argument(
        "-f",
        "--file",
        type=str,
        default=default_usage_file,
        help=f"指定消费数据文件的路径。\n(默认: {default_usage_file})",
    )

    args = parser.parse_args()

    if args.days <= 0:
        print(Fore.RED + "错误: --days 参数必须是一个正数。")
        sys.exit(1)

    analyzer = UsageAnalyzer(usage_file_path=args.file)
    analyzer.display_report(days=args.days)


if __name__ == "__main__":
    main()
