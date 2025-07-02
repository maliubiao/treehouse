import subprocess
from dataclasses import dataclass
from datetime import date


class GitStatsError(Exception):
    """Custom exception for errors during Git stats collection."""


@dataclass
class CommitStats:
    """
    A data class to hold Git commit statistics for a specific date.
    """

    date: date
    commits: int
    additions: int
    deletions: int

    @property
    def net_changes(self) -> int:
        """Calculate the net change in lines of code."""
        return self.additions - self.deletions


class GitStatsCollector:
    """
    Collects commit statistics from a Git repository for a given date.
    """

    def __init__(self, repo_path: str = "."):
        """
        Initializes the collector.

        Args:
            repo_path (str): The file path to the Git repository. Defaults to the current directory.
        """
        self.repo_path = repo_path

    def _run_git_command(self, command: list[str]) -> str:
        """
        A helper method to run a Git command and handle potential errors.

        Args:
            command (list[str]): The Git command to execute as a list of arguments.

        Raises:
            GitStatsError: If Git is not installed, the path is not a repo, or the command fails.

        Returns:
            str: The stdout from the command.
        """
        try:
            return subprocess.check_output(command, cwd=self.repo_path, text=True, stderr=subprocess.PIPE)
        except FileNotFoundError as exc:
            raise GitStatsError("Git command not found. Please ensure Git is installed and in your PATH.") from exc
        except subprocess.CalledProcessError as e:
            error_output = e.stderr.lower()
            if "not a git repository" in error_output:
                raise GitStatsError(f"The path '{self.repo_path}' is not a Git repository.") from e
            raise GitStatsError(f"Git command failed with exit code {e.returncode}:\n{e.stderr.strip()}") from e

    def _get_current_user_email(self) -> str | None:
        """Gets the email of the current git user from config."""
        try:
            email_cmd = ["git", "config", "user.email"]
            email = self._run_git_command(email_cmd).strip()
            return email if email else None
        except GitStatsError:
            # This can happen if user.email is not set, which is a valid state.
            # We interpret it as no current user email is available.
            return None

    def _resolve_author(self, author_filter: str | None) -> str | None:
        """
        Resolves the author argument to a specific email if 'CURRENT_USER' is provided.

        Args:
            author_filter: The author filter from the public method.

        Returns:
            The specific author email, or None if all authors should be included.

        Raises:
            GitStatsError: If 'CURRENT_USER' is used but the git user email cannot be determined.
        """
        if author_filter != "CURRENT_USER":
            return author_filter

        current_user_email = self._get_current_user_email()
        if not current_user_email:
            raise GitStatsError(
                "Could not determine git user. Please run 'git config --global user.email \"you@example.com\"'\n"
                "Alternatively, specify an author with --author <email> or use --all-authors."
            )
        return current_user_email

    def _build_query_command(self, base_command: list[str], target_date: date, author: str | None) -> list[str]:
        """
        Constructs a git command with author and date filters.

        Args:
            base_command: The base git command as a list of strings.
            target_date: The date to filter by.
            author: The author email to filter by, if any.

        Returns:
            The fully constructed git command.
        """
        command = base_command[:]
        since_str = target_date.strftime("%Y-%m-%d 00:00:00")
        until_str = target_date.strftime("%Y-%m-%d 23:59:59")

        if author:
            command.append(f"--author={author}")

        command.extend(["--since", since_str, "--until", until_str])
        return command

    def _parse_numstat_output(self, stats_output: str) -> tuple[int, int]:
        """
        Parses the output of 'git log --numstat' to get total additions and deletions.

        Args:
            stats_output: The string output from the git command.

        Returns:
            A tuple containing total additions and total deletions.
        """
        total_additions = 0
        total_deletions = 0
        for line in stats_output.splitlines():
            if not line:
                continue
            parts = line.split("\t")
            # Handle binary files where additions/deletions are '-', by ignoring them.
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                total_additions += int(parts[0])
                total_deletions += int(parts[1])
        return total_additions, total_deletions

    def get_stats_for_date(self, target_date: date, author: str | None = "CURRENT_USER") -> CommitStats:
        """
        Retrieves commit statistics for a specific date and author.

        Args:
            target_date (date): The date for which to retrieve stats.
            author (str | None): The author's email to filter commits by.
                If "CURRENT_USER" (default), it uses the current git user's email.
                If None, it aggregates stats from all authors.

        Returns:
            CommitStats: An object containing the statistics for the given date.

        Raises:
            GitStatsError: If 'CURRENT_USER' is used and git user.email is not configured.
        """
        final_author = self._resolve_author(author)

        # 1. Get the total number of commits for the day
        base_count_cmd = ["git", "rev-list", "--all", "--count"]
        count_cmd = self._build_query_command(base_count_cmd, target_date, final_author)
        commit_count_str = self._run_git_command(count_cmd)
        commit_count = int(commit_count_str.strip())

        if commit_count == 0:
            return CommitStats(date=target_date, commits=0, additions=0, deletions=0)

        # 2. Get the aggregated additions and deletions for the day
        base_stats_cmd = ["git", "log", "--all", "--pretty=tformat:", "--numstat"]
        stats_cmd = self._build_query_command(base_stats_cmd, target_date, final_author)
        stats_output = self._run_git_command(stats_cmd)

        total_additions, total_deletions = self._parse_numstat_output(stats_output)

        return CommitStats(
            date=target_date,
            commits=commit_count,
            additions=total_additions,
            deletions=total_deletions,
        )
