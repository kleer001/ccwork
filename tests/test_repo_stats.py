"""Tests for the dashboard git stats aggregator.

`gather_stats` shells out to real git against throwaway repos created in
tmp dirs. Windows are rolling 7-day spans anchored to a pinned `now`, so
tests pin dates relative to it. `relative_time`, `churn_tag`,
`fingerprints`, and `summarize` are pure and tested directly. A non-repo
path must be skipped, never raise — the splash depends on that.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from src.core.repo_stats import (
    COOLER_PRIOR_FLOOR,
    RADAR_AXES,
    TREND_WEEKS,
    RepoStats,
    RepoWeek,
    churn_tag,
    fingerprints,
    gather_stats,
    relative_time,
    summarize,
)

# Pinned "now" for every rolling window (a Wednesday noon).
NOW = datetime(2026, 6, 3, 12, 0, 0)


def _iso(days_ago: float, hour: int = 9) -> str:
    d = NOW - timedelta(days=days_ago)
    return d.replace(hour=hour, minute=0, second=0).isoformat()


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


def _commit(repo: Path, name: str, msg: str, date: str, content: str | None = None) -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(content if content is not None else name)
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
    stats = gather_stats([(str(plain), "notarepo")], now=NOW)
    assert stats.repo_count == 0
    assert stats.week_total == 0
    assert stats.weekly_totals == [0] * TREND_WEEKS


def test_rolling_window_and_prior_week(tmp_path: Path) -> None:
    repo = tmp_path / "r1"
    _make_repo(repo)
    _commit(repo, "old", "prior week", _iso(10))     # prior window
    _commit(repo, "older", "prior week 2", _iso(9))  # prior window
    _commit(repo, "a", "in window", _iso(5))
    _commit(repo, "b", "in window 2", _iso(1))
    (repo / "wip").write_text("dirty")               # uncommitted

    stats = gather_stats([(str(repo), "r1")], now=NOW)

    assert stats.repo_count == 1
    assert len(stats.active) == 1
    r = stats.active[0]
    assert r.commits == 2
    assert r.prior_commits == 2
    assert r.delta == 0
    assert r.dirty is True
    assert r.lifetime_commits == 4
    assert stats.week_total == 2
    # trend histogram: 2 in the current week, 2 in the one before
    assert stats.weekly_totals[-1] == 2
    assert stats.weekly_totals[-2] == 2
    assert sum(stats.weekly_totals) == 4


def test_churn_new_files_breadth_and_types(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _make_repo(repo)
    _commit(repo, "base.py", "pre-window", _iso(20), content="a\nb\nc\n")
    _commit(repo, "one.py", "add one", _iso(3), content="x\ny\n")          # +2, new
    _commit(repo, "two.md", "add two", _iso(2), content="m\n")             # +1, new
    _commit(repo, "base.py", "edit base", _iso(1), content="a\n")          # -2 (keep 1 of 3)

    stats = gather_stats([(str(repo), "r")], now=NOW)
    r = stats.active[0]
    assert r.commits == 3
    assert r.insertions == 3      # 2 + 1 in the window
    assert r.deletions == 2       # base.py shrank by 2
    assert r.net == 1
    assert r.new_files == 2       # one.py, two.md (base.py predates window)
    assert r.files_changed == 3   # one.py, two.md, base.py
    assert r.file_types == 2      # py, md
    assert r.lines_per_commit == round(5 / 3)


def test_new_from_zero_and_quiet_split(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh"
    _make_repo(fresh)
    _commit(fresh, "f", "first ever", _iso(4))

    idle = tmp_path / "idle"
    _make_repo(idle)
    _commit(idle, "f", "long ago", _iso(30))

    stats = gather_stats([(str(fresh), "fresh"), (str(idle), "idle")], now=NOW)
    assert [r.name for r in stats.active] == ["fresh"]
    assert stats.active[0].new_from_zero is True
    assert [r.name for r in stats.quiet] == ["idle"]
    assert stats.quiet[0].lifetime_commits == 1


def test_release_detected_only_within_window(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _make_repo(repo)
    _commit(repo, "f", "c1", _iso(3))
    _git(repo, "tag", "v1.1.0", env_date=_iso(2))
    stats = gather_stats([(str(repo), "r")], now=NOW)
    assert stats.active[0].release == "v1.1.0"
    assert stats.releases and stats.releases[0].name == "r"

    old = tmp_path / "old"
    _make_repo(old)
    _commit(old, "f", "c1", _iso(20))
    _git(old, "tag", "v0.9.0", env_date=_iso(20))
    _commit(old, "g", "c2", _iso(1))
    stats = gather_stats([(str(old), "old")], now=NOW)
    assert stats.active[0].release is None


def test_active_sorted_newest_first_quiet_by_lifetime(tmp_path: Path) -> None:
    a = tmp_path / "a"; _make_repo(a)
    _commit(a, "f", "c", _iso(5))
    b = tmp_path / "b"; _make_repo(b)
    _commit(b, "f", "c", _iso(1))
    q1 = tmp_path / "q1"; _make_repo(q1)
    _commit(q1, "f", "c", _iso(30))
    q2 = tmp_path / "q2"; _make_repo(q2)
    _commit(q2, "f", "c1", _iso(31))
    _commit(q2, "g", "c2", _iso(30))

    stats = gather_stats(
        [(str(a), "a"), (str(b), "b"), (str(q1), "q1"), (str(q2), "q2")], now=NOW)
    assert [r.name for r in stats.active] == ["b", "a"]
    assert [r.name for r in stats.quiet] == ["q2", "q1"]


def test_merge_commits_excluded(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _make_repo(repo)
    _commit(repo, "f", "base", _iso(6))
    _git(repo, "checkout", "-q", "-b", "feat")
    _commit(repo, "g", "feature", _iso(5))
    _git(repo, "checkout", "-q", "-")
    _commit(repo, "h", "mainline", _iso(4))
    _git(repo, "merge", "--no-ff", "-q", "-m", "merge feat", "feat",
         env_date=_iso(3))

    stats = gather_stats([(str(repo), "r")], now=NOW)
    r = stats.active[0]
    assert r.commits == 3          # merge commit not counted
    assert r.lifetime_commits == 3


def test_malformed_timestamp_is_skipped_not_raised(monkeypatch) -> None:
    """git %ct is external input; a garbage/out-of-range value must be
    skipped, upholding the 'never raises on a bad repo' contract."""
    import src.core.repo_stats as rs

    def fake_run_git(path, args, timeout=3):
        if args[0] == "status":
            return ""                                    # clean repo
        if args[0] == "log" and "--numstat" in args:
            return "\x0199999999999999999999\n\x01notanumber\n"
        if args[0] == "log" and "--format=%ct" in args:
            return "99999999999999999999\nnotanumber\n"
        return ""

    monkeypatch.setattr(rs, "_run_git", fake_run_git)
    stats = rs.gather_stats([("/x", "x")], now=NOW)      # must not raise
    assert stats.repo_count == 1
    assert stats.active[0].commits == 2                  # counted, stamps dropped
    assert stats.weekly_totals == [0] * TREND_WEEKS


def test_dedups_by_realpath(tmp_path: Path) -> None:
    """Two sidebar rows on one path must count once."""
    repo = tmp_path / "r"
    _make_repo(repo)
    _commit(repo, "f", "c", _iso(1))
    stats = gather_stats([(str(repo), "r"), (str(repo), "r (II)")], now=NOW)
    assert stats.repo_count == 1
    assert stats.week_total == 1


# ── churn_tag ──

def _rw(ins: int, dels: int, **kw) -> RepoWeek:
    return RepoWeek(name="x", path="/x", insertions=ins, deletions=dels, **kw)


def test_churn_tag_buckets() -> None:
    assert churn_tag(_rw(95, 5)) == "mostly new work"
    assert churn_tag(_rw(75, 25)) == "growing"
    assert churn_tag(_rw(30, 70)) == "trimming"
    assert churn_tag(_rw(50, 50)) == "balanced"
    assert churn_tag(_rw(0, 0)) == "balanced"


# ── fingerprints ──

def test_fingerprints_normalize_to_busiest_per_axis() -> None:
    big = RepoWeek(name="big", path="/big", commits=72, insertions=11361,
                   deletions=3724, new_files=57, files_changed=61, file_types=7)
    mid = RepoWeek(name="mid", path="/mid", commits=29, insertions=5032,
                   deletions=372, new_files=33, files_changed=66, file_types=5)
    fps = fingerprints([big, mid])
    assert set(fps) == {"/big", "/mid"}
    assert len(fps["/big"]) == len(RADAR_AXES)
    # Vol: big is the max → 1.0; mid = 29/72
    assert fps["/big"][0] == 1.0
    assert abs(fps["/mid"][0] - 29 / 72) < 1e-9
    # Breadth: mid touched more files → mid is 1.0 there
    assert fps["/mid"][3] == 1.0
    assert abs(fps["/big"][3] - 61 / 66) < 1e-9
    # Rework: deletions' share of churn, normalized to the max share
    big_share = 3724 / (11361 + 3724)
    mid_share = 372 / (5032 + 372)
    assert fps["/big"][4] == 1.0
    assert abs(fps["/mid"][4] - mid_share / big_share) < 1e-9
    # all spokes clamped to 0..1
    assert all(0.0 <= v <= 1.0 for fp in fps.values() for v in fp)


def test_fingerprints_zero_axis_stays_zero() -> None:
    r = RepoWeek(name="r", path="/r", commits=3)   # no churn at all
    fps = fingerprints([r])
    assert fps["/r"][0] == 1.0                     # Vol normalizes to itself
    assert fps["/r"][1] == 0.0                     # Churn axis max is 0 → 0.0


# ── summarize ──

def _stats(active: list[RepoWeek], weekly: list[int] | None = None) -> RepoStats:
    s = RepoStats(active=active)
    if weekly is not None:
        s.weekly_totals = weekly
    else:
        total = sum(r.commits for r in active)
        s.weekly_totals = [0, 0, 0, 10, 10, 10, 10, total]
    return s


def test_summarize_idle_week() -> None:
    out = summarize(RepoStats(), now=NOW)
    assert "quiet" in out.lower() or "no commits" in out.lower()


def test_summarize_tone_growing_vs_quieter() -> None:
    grow = _stats([RepoWeek(name="r", path="/r", commits=20)],
                  weekly=[0, 0, 0, 10, 10, 10, 10, 20])   # avg 10, ratio 2.0
    calm = _stats([RepoWeek(name="r", path="/r", commits=5)],
                  weekly=[0, 0, 0, 10, 10, 10, 10, 5])    # ratio 0.5
    g = summarize(grow, now=NOW)
    q = summarize(calm, now=NOW)
    assert g != q
    assert g.split(".")[0] != q.split(".")[0]


def test_summarize_standout_priority_release_over_kickoff() -> None:
    rel = RepoWeek(name="shipper", path="/s", commits=2, release="v1.1.0",
                   release_ts=int(NOW.timestamp()))
    fresh = RepoWeek(name="newbie", path="/n", commits=40, insertions=11000,
                     new_from_zero=True)
    grower = RepoWeek(name="steady", path="/g", commits=30, prior_commits=10)
    out = summarize(_stats([fresh, rel, grower]), now=NOW)
    # release clause present, colored, and precedes the kickoff clause
    assert "shipper" in out and "v1.1.0" in out and "color:" in out
    assert out.index("shipper") < out.index("newbie")
    # only two standouts — the grower is dropped
    assert "steady" not in out


def test_summarize_kickoff_mentions_commits_and_lines() -> None:
    fresh = RepoWeek(name="newbie", path="/n", commits=40, insertions=11361,
                     new_from_zero=True)
    out = summarize(_stats([fresh]), now=NOW)
    assert "newbie" in out
    assert "40 commits" in out
    assert "+11k" in out


def test_summarize_coolers_respect_floor() -> None:
    big_cool = RepoWeek(name="dog", path="/d", commits=29,
                        prior_commits=61)                       # counts
    tiny_cool = RepoWeek(name="tiny", path="/t", commits=1,
                         prior_commits=COOLER_PRIOR_FLOOR - 1)  # under floor
    out = summarize(_stats([big_cool, tiny_cool]), now=NOW)
    assert "dog" in out
    assert "tiny" not in out


def test_summarize_deterministic_and_varies_by_week() -> None:
    s = _stats([RepoWeek(name="r", path="/r", commits=20)])
    a = summarize(s, now=NOW)
    b = summarize(s, now=NOW)
    assert a == b
    other_weeks = {summarize(s, now=NOW + timedelta(weeks=k)) for k in range(1, 4)}
    assert any(o != a for o in other_weeks)


def test_summarize_escapes_html_in_names() -> None:
    r = RepoWeek(name="a<b&c", path="/x", commits=20, prior_commits=5)
    out = summarize(_stats([r]), now=NOW)
    assert "a<b&c" not in out
    assert "a&lt;b&amp;c" in out
