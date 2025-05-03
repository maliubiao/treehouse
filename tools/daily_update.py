import locale
import subprocess
import sys
from datetime import datetime, timedelta


def get_terminal_language():
    terminal_lang = locale.getlocale()[0]
    return terminal_lang


def get_git_commit_stats(days_ago=0):
    # Get the date for the specified number of days ago
    date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")

    # Get the list of commits for the specified date
    commit_list = (
        subprocess.check_output(
            [
                "git",
                "log",
                f'--since="{date} 00:00:00"',
                f'--until="{date} 23:59:59"',
                "--pretty=format:%H",
                "--date=local",
            ]
        )
        .decode("utf-8")
        .splitlines()
    )

    # Initialize counters
    total_additions = 0
    total_deletions = 0

    # Iterate through each commit and get the diff stats
    for commit in commit_list:
        diff_stats = subprocess.check_output(
            ["git", "diff", "--shortstat", f"{commit}^..{commit}"]
        ).decode("utf-8")
        if diff_stats:
            stats = diff_stats.strip().split(",")
            for stat in stats:
                if "insertion" in stat:
                    total_additions += int(stat.strip().split()[0])
                elif "deletion" in stat:
                    total_deletions += int(stat.strip().split()[0])

    # Calculate net changes
    net_changes = total_additions - total_deletions

    return {
        "date": date,
        "commits": len(commit_list),
        "additions": total_additions,
        "deletions": total_deletions,
        "net_changes": net_changes,
    }


if __name__ == "__main__":
    commit_stats = get_git_commit_stats()
    terminal_lang = get_terminal_language()
    COLOR_GREEN = "\033[1;32m" if sys.stdout.isatty() else ""
    COLOR_RESET = "\033[0m" if sys.stdout.isatty() else ""
    if terminal_lang and "zh" in terminal_lang.lower():
        print(f"{COLOR_GREEN}日期: {commit_stats['date']}{COLOR_RESET}")
        print(f"{COLOR_GREEN}提交次数: {commit_stats['commits']}{COLOR_RESET}")
        print(f"{COLOR_GREEN}新增行数: {commit_stats['additions']}{COLOR_RESET}")
        print(f"{COLOR_GREEN}删除行数: {commit_stats['deletions']}{COLOR_RESET}")
        print(f"{COLOR_GREEN}净变化: {commit_stats['net_changes']}{COLOR_RESET}")
    else:
        print(f"{COLOR_GREEN}Date: {commit_stats['date']}{COLOR_RESET}")
        print(f"{COLOR_GREEN}Commits: {commit_stats['commits']}{COLOR_RESET}")
        print(f"{COLOR_GREEN}Additions: {commit_stats['additions']}{COLOR_RESET}")
        print(f"{COLOR_GREEN}Deletions: {commit_stats['deletions']}{COLOR_RESET}")
        print(f"{COLOR_GREEN}Net Changes: {commit_stats['net_changes']}{COLOR_RESET}")
