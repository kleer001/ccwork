"""Best-effort git activity stats for the splash screen.

Aggregates commit / dirty counts across the tracked repos by shelling out
to git, the same way `repo_store` does. Errors are per-repo and swallowed:
a repo that can't be read (renamed, deleted, not a git tree) is skipped and
the splash shows whatever could be gathered. Nothing here ever raises on a
bad repo — the splash must not break.

The commit histogram is the *current calendar week*, Monday-anchored:
`daily_counts` is always length WEEK_DAYS (Mon→Sun) so the chart never
changes width; days after today are simply 0. `today_index` (0=Mon … 6=Sun)
lets the UI dim the not-yet-happened days. `commits_this_week` is the sum.

Pure logic, no Qt. The UI layer runs `gather_stats` on a worker thread
(git forks block) and feeds the result through `relative_time`.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

log = logging.getLogger(__name__)

WEEK_DAYS = 7


@dataclass
class RecentActivity:
    name: str       # repo display name
    subject: str    # commit subject line
    ts: int         # epoch seconds of that commit


@dataclass
class RepoStats:
    repo_count: int = 0
    dirty_count: int = 0
    dirty_names: list[str] = field(default_factory=list)
    commits_this_week: int = 0
    # One bucket per weekday, Monday first. Length WEEK_DAYS; future days 0.
    daily_counts: list[int] = field(default_factory=lambda: [0] * WEEK_DAYS)
    today_index: int = 0   # 0=Mon … 6=Sun, the last "real" column
    recent: RecentActivity | None = None


def _run_git(path: str | os.PathLike[str], args: list[str], timeout: int = 3) -> str | None:
    """Run `git -C path <args>`; return stdout, or None on any failure.

    Mirrors `repo_store`'s git helpers. A None return means "skip this
    repo" — the caller never distinguishes the failure modes."""
    try:
        r = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        log.debug("repo_stats: git %s failed for %s (%s)", args, path, e)
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def gather_stats(repos: Iterable[tuple[str, str]], now: datetime | None = None) -> RepoStats:
    """Aggregate git stats over `repos`, an iterable of (path, display_name).

    Dedups by real path so duplicate sidebar rows sharing one path don't
    double-count. `now` defaults to the local current time."""
    now = now or datetime.now()
    today = now.date()
    today_index = today.weekday()                      # 0=Mon … 6=Sun
    week_start = today - timedelta(days=today_index)    # this week's Monday
    since = week_start.strftime("%Y-%m-%d 00:00:00")

    stats = RepoStats(today_index=today_index)
    seen: set[str] = set()
    for path, name in repos:
        try:
            key = os.path.realpath(path)
        except OSError:
            continue
        if key in seen:
            continue

        # `status --porcelain` doubles as the "is this a readable git tree?"
        # probe — None means not-a-repo / gone, so skip the row entirely.
        status = _run_git(path, ["status", "--porcelain"])
        if status is None:
            continue
        seen.add(key)
        stats.repo_count += 1
        if status.strip():
            stats.dirty_count += 1
            stats.dirty_names.append(name)

        log_out = _run_git(path, ["log", "--since", since, "--format=%ct"])
        if log_out:
            for token in log_out.split():
                try:
                    ct = int(token)
                except ValueError:
                    continue
                idx = (datetime.fromtimestamp(ct).date() - week_start).days
                if 0 <= idx < WEEK_DAYS:
                    stats.daily_counts[idx] += 1

        head = _run_git(path, ["log", "-1", "--format=%ct%x00%s"])
        if head and "\x00" in head:
            ts_s, subject = head.strip().split("\x00", 1)
            try:
                ts = int(ts_s)
            except ValueError:
                continue
            if stats.recent is None or ts > stats.recent.ts:
                stats.recent = RecentActivity(name=name, subject=subject.strip(), ts=ts)

    stats.commits_this_week = sum(stats.daily_counts)
    return stats


def relative_time(ts: int, now: datetime | None = None) -> str:
    """Coarse "2h ago" / "3d ago" string for an epoch timestamp."""
    now = now or datetime.now()
    secs = int((now - datetime.fromtimestamp(ts)).total_seconds())
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks}w ago"
    return f"{days // 30}mo ago"
