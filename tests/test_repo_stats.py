"""Tests for the splash-screen git stats aggregator.

`gather_stats` shells out to real git against throwaway repos created in
tmp dirs. The histogram is the current calendar week (Monday-anchored),
so tests pin `now` to a known weekday. `relative_time` is pure and
tested directly. A non-repo path must be skipped, never raise — the
splash depends on that.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from src.core.repo_stats import (
    WEEK_DAYS,
    gather_stats,
    relative_time,
)

# A Wednesday (2026-06-03): weekday() == 2, week_start = Mon 2026-06-01.
WED = datetime(2026, 6, 3, 12, 0, 0)


def _git(cwd: Path, *args: str, env_date: str | None = None) -> None:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": "/usr/bin:/bin",
    }
    if env_date is not None:
        env["GIT_AUTHOR_DATE"] = env_date
        env["GIT_COMMITTER_DATE"] = env_date
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True, env=env)


def _make_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")


def _commit(repo: Path, name: str, msg: str, date: str) -> None:
    (repo / name).write_text(name)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", msg, env_date=date)


# ── relative_time ──

def test_relative_time_buckets() -> None:
    now = datetime(2026, 6, 2, 12, 0, 0)
    ts = lambda **kw: int((now - timedelta(**kw)).timestamp())
    assert relative_time(ts(seconds=10), now) == "just now"
    assert relative_time(ts(minutes=5), now) == "5m ago"
    assert relative_time(ts(hours=3), now) == "3h ago"
    assert relative_time(ts(days=2), now) == "2d ago"
    assert relative_time(ts(days=10), now) == "1w ago"


# ── gather_stats ──

def test_skips_non_git_path(tmp_path: Path) -> None:
    """A plain directory must be skipped silently, not raise."""
    plain = tmp_path / "notarepo"
    plain.mkdir()
    stats = gather_stats([(str(plain), "notarepo")], now=WED)
    assert stats.repo_count == 0
    assert stats.dirty_count == 0
    assert stats.commits_this_week == 0
    assert stats.daily_counts == [0] * WEEK_DAYS
    assert stats.recent is None
    assert stats.today_index == 2  # Wednesday


def test_week_is_monday_anchored_and_excludes_last_week(tmp_path: Path) -> None:
    repo = tmp_path / "r1"
    _make_repo(repo)
    _commit(repo, "old", "last week", "2026-05-28T09:00:00")   # prev week → excluded
    _commit(repo, "a", "monday", "2026-06-01T09:00:00")        # idx 0
    _commit(repo, "b", "wed one", "2026-06-03T08:00:00")       # idx 2 (today)
    _commit(repo, "c", "latest", "2026-06-03T10:00:00")        # idx 2 (today)
    (repo / "wip").write_text("dirty")                         # uncommitted

    stats = gather_stats([(str(repo), "r1")], now=WED)

    assert stats.repo_count == 1
    assert stats.dirty_count == 1
    assert stats.dirty_names == ["r1"]
    assert stats.today_index == 2
    assert len(stats.daily_counts) == WEEK_DAYS
    assert stats.daily_counts == [1, 0, 2, 0, 0, 0, 0]
    assert stats.commits_this_week == 3   # last-week commit excluded
    assert stats.recent is not None
    assert stats.recent.subject == "latest"
    assert stats.recent.name == "r1"


def test_dirty_names_aggregate_across_repos(tmp_path: Path) -> None:
    clean = tmp_path / "clean"; _make_repo(clean)
    _commit(clean, "f", "c", "2026-06-01T08:00:00")
    messy = tmp_path / "messy"; _make_repo(messy)
    _commit(messy, "f", "c", "2026-06-01T08:00:00")
    (messy / "wip").write_text("x")

    stats = gather_stats([(str(clean), "clean"), (str(messy), "messy")], now=WED)
    assert stats.repo_count == 2
    assert stats.dirty_count == 1
    assert stats.dirty_names == ["messy"]


def test_dedups_by_realpath(tmp_path: Path) -> None:
    """Two sidebar rows on one path must count once."""
    repo = tmp_path / "r"
    _make_repo(repo)
    _commit(repo, "f", "c", "2026-06-01T08:00:00")
    stats = gather_stats([(str(repo), "r"), (str(repo), "r (II)")], now=WED)
    assert stats.repo_count == 1
    assert stats.commits_this_week == 1
