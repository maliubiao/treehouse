from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class SourceStatistics:
    def __init__(self, pattern_stats, total_files, total_symbols, skipped_symbols):
        self.pattern_stats = pattern_stats
        self.total_files = total_files
        self.total_symbols = total_symbols
        self.skipped_symbols = skipped_symbols
        self._console = Console()

    def display(self):
        """显示源文件过滤统计信息"""
        if not self.pattern_stats or not self.total_symbols:
            return

        table = Table(title="Source File Filtering Statistics", show_header=True, header_style="bold magenta")
        table.add_column("Pattern", style="cyan")
        table.add_column("Files Skipped", justify="right")
        table.add_column("Symbols Skipped", justify="right")
        table.add_column("Coverage", justify="right")

        # 添加每个模式的统计
        total_skipped_files = 0
        total_skipped_symbols = 0

        for pattern, stats in self.pattern_stats.items():
            skipped_files = stats["files"]
            skipped_symbols = stats["symbols"]
            coverage = f"{skipped_symbols / self.total_symbols:.1%}" if self.total_symbols else "0%"

            table.add_row(pattern, str(skipped_files), str(skipped_symbols), coverage)

            total_skipped_files += skipped_files
            total_skipped_symbols += skipped_symbols

        # 添加总计行
        total_coverage = f"{total_skipped_symbols / self.total_symbols:.1%}" if self.total_symbols else "0%"
        table.add_row(
            "[bold]TOTAL[/bold]",
            f"[bold]{total_skipped_files}[/bold]",
            f"[bold]{total_skipped_symbols}[/bold]",
            f"[bold]{total_coverage}[/bold]",
            style="bold yellow",
        )

        # 添加保留统计
        preserved_files = self.total_files - total_skipped_files
        preserved_symbols = self.total_symbols - total_skipped_symbols
        preserved_coverage = f"{preserved_symbols / self.total_symbols:.1%}" if self.total_symbols else "0%"

        table.add_row(
            "[bold green]PRESERVED[/bold green]",
            f"[bold green]{preserved_files}[/bold green]",
            f"[bold green]{preserved_symbols}[/bold green]",
            f"[bold green]{preserved_coverage}[/bold green]",
            style="bold green",
        )

        # 添加全局统计
        global_stats = Table.grid()
        global_stats.add_row(f"Total files processed: [bold]{self.total_files}[/bold]")
        global_stats.add_row(f"Total symbols processed: [bold]{self.total_symbols}[/bold]")
        global_stats.add_row(f"Symbol filtering efficiency: [bold]{total_coverage}[/bold]")

        # 输出面板
        self._console.print(Panel.fit(global_stats, title="[bold]Global Statistics[/bold]", border_style="blue"))
        self._console.print(table)
