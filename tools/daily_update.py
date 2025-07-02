import argparse
import locale
import os
import sys
from datetime import date, datetime, timedelta

# Add project root to sys.path to ensure modules can be found
# when running the script from any location. This is a robust way
# to handle imports in a script within a larger project.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)


try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except ImportError:
    print("Error: 'rich' library not found.", file=sys.stderr)
    print("Please install it by running: pip install rich", file=sys.stderr)
    sys.exit(1)

from tools.git_utils.stats_collector import CommitStats, GitStatsCollector, GitStatsError


def get_terminal_language() -> str:
    """Detects the terminal's language preference."""
    try:
        terminal_lang = locale.getlocale()[0]
        return terminal_lang or "en"
    except (ValueError, TypeError):
        return "en"


def parse_date_argument(date_str: str) -> date:
    """
    Parses a date string from the command line into a date object.
    Supports 'today', 'yesterday', and 'YYYY-MM-DD' formats.
    """
    if date_str.lower() == "today":
        return date.today()
    if date_str.lower() == "yesterday":
        return date.today() - timedelta(days=1)
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid date format: '{date_str}'. Please use YYYY-MM-DD, 'today', or 'yesterday'.") from exc


def create_stats_presenter(stats: CommitStats, lang: str, author_display: str | None = None):
    """Creates a visually appealing presentation of the stats using rich."""
    is_zh = "zh" in lang.lower()

    title = "Git Daily Update" if not is_zh else "Git 当日统计"
    if author_display:
        title += f" ({author_display})"

    labels = {
        "date": "日期" if is_zh else "Date",
        "author": "作者" if is_zh else "Author",
        "commits": "提交次数" if is_zh else "Commits",
        "additions": "新增行数" if is_zh else "Additions",
        "deletions": "删除行数" if is_zh else "Deletions",
        "net": "净变化" if is_zh else "Net Changes",
    }

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Metric", style="dim")
    table.add_column("Value", style="bold")

    table.add_row(f"{labels['date']}:", str(stats.date))
    table.add_row(f"{labels['commits']}:", str(stats.commits))
    table.add_row(f"{labels['additions']}:", f"[green]+{stats.additions}[/green]")
    table.add_row(f"{labels['deletions']}:", f"[red]-{stats.deletions}[/red]")

    net_style = "green" if stats.net_changes >= 0 else "red"
    net_sign = "+" if stats.net_changes >= 0 else ""
    table.add_row(
        f"{labels['net']}:",
        f"[{net_style}]{net_sign}{stats.net_changes}[/{net_style}]",
    )

    return Panel(
        table,
        title=f"[bold cyan]{title}[/bold cyan]",
        border_style="blue",
        expand=False,
    )


def main():
    """
    Main function to parse arguments, collect stats, and display them.
    """
    parser = argparse.ArgumentParser(
        description="A tool to display daily Git commit statistics with a modern UI.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--date",
        help="The date to fetch stats for.\nFormats: YYYY-MM-DD, 'today', 'yesterday'.\nDefault: 'today'.",
        default="today",
    )

    author_group = parser.add_mutually_exclusive_group()
    author_group.add_argument(
        "-a",
        "--author",
        type=str,
        help="Filter by a specific author's email.\nDefaults to the current git user.",
    )
    author_group.add_argument(
        "--all-authors",
        action="store_true",
        help="Aggregate stats from all authors instead of filtering by the current user.",
    )

    args = parser.parse_args()
    console = Console()

    try:
        target_date = parse_date_argument(args.date)

        # Determine author for filtering and for display purposes
        author_filter: str | None = "CURRENT_USER"  # Special value for collector
        author_display: str | None = "current user"
        if args.author:
            author_filter = args.author
            author_display = args.author
        elif args.all_authors:
            author_filter = None
            author_display = "All Authors"

        collector = GitStatsCollector()
        commit_stats = collector.get_stats_for_date(target_date, author=author_filter)

        lang = get_terminal_language()
        presentation = create_stats_presenter(commit_stats, lang, author_display=author_display)
        console.print(presentation)

    except (GitStatsError, ValueError) as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
