from rich.console import Console
from rich.panel import Panel
from rich.table import Table


class SourceStatistics:
    """
    Displays statistics about source file filtering in a rich, formatted table.
    """

    def __init__(self, pattern_stats, total_files, total_symbols, skipped_symbols):
        self.pattern_stats = pattern_stats
        self.total_files = total_files
        self.total_symbols = total_symbols
        self.skipped_symbols = skipped_symbols
        self._console = Console()

    def display(self):
        """
        Renders and prints the statistics report to the console.
        """
        if not self.pattern_stats and self.total_symbols == 0:
            self._console.print("[yellow]No source filtering statistics to display.[/yellow]")
            return

        # --- Summary Panel ---
        total_skipped_symbols = sum(stats["symbols"] for stats in self.pattern_stats.values())
        preserved_symbols = self.total_symbols - total_skipped_symbols

        efficiency = f"{(total_skipped_symbols / self.total_symbols):.1%}" if self.total_symbols > 0 else "N/A"

        summary_grid = Table.grid(expand=True)
        summary_grid.add_column(style="bold cyan")
        summary_grid.add_column(justify="right", style="bold")
        summary_grid.add_row("Total Symbols Processed:", f"{self.total_symbols:,}")
        summary_grid.add_row("Symbols Skipped:", f"[red]{total_skipped_symbols:,}[/red]")
        summary_grid.add_row("Symbols Preserved:", f"[green]{preserved_symbols:,}[/green]")
        summary_grid.add_row("Filtering Efficiency:", f"[yellow]{efficiency}[/yellow]")

        self._console.print(Panel(summary_grid, title="[bold]Source Filtering Summary[/bold]", border_style="blue"))

        # --- Detailed Pattern Table ---
        if self.pattern_stats:
            table = Table(title="[bold]Breakdown by Skip Pattern[/bold]", show_header=True, header_style="bold magenta")
            table.add_column("Pattern", style="cyan", no_wrap=True)
            table.add_column("Files Skipped", justify="right", style="green")
            table.add_column("Symbols Skipped", justify="right", style="red")
            table.add_column("Coverage", justify="right", style="yellow")

            for pattern, stats in sorted(self.pattern_stats.items()):
                skipped_files = stats["files"]
                skipped_symbols = stats["symbols"]
                coverage = f"{(skipped_symbols / self.total_symbols):.1%}" if self.total_symbols > 0 else "0.0%"
                table.add_row(pattern, f"{skipped_files:,}", f"{skipped_symbols:,}", coverage)

            self._console.print(table)
