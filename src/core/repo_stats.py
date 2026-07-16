"""Best-effort git activity stats for the splash dashboard.

Gathers per-repo activity over a **rolling 7-day window, merges excluded**
by shelling out to git, the same way `repo_store` does. Errors are
per-repo and swallowed: a repo that can't be read (renamed, deleted, not
a git tree) is skipped and the dashboard shows whatever could be
gathered. Nothing here ever raises on a bad repo — the splash must not
break.

Every repo becomes a `RepoWeek` snapshot (commits, churn, new files,
breadth, file types, release tag, lifetime size). Repos with commits in
the window are `active`, the rest `quiet`. `weekly_totals` is an
8-trailing-week commit histogram across all repos for the trend hero.
`fingerprints` turns the active set into 0..1 radar spokes, each axis
normalized to the busiest active repo this window. `summarize` renders
the deterministic narrative sentence (template NLG, no LLM).

Pure logic, no Qt. The UI layer runs `gather_stats` on a worker thread
(git forks block) and feeds the result through `relative_time`.
"""

from __future__ import annotations

import html
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

log = logging.getLogger(__name__)

ROLL_DAYS = 7                    # the rolling activity window
TREND_WEEKS = 8                  # trailing weeks in the trend histogram
_WEEK_SECS = ROLL_DAYS * 86400

# Radar spokes, in paint order (top, then clockwise).
RADAR_AXES = ("Vol", "Churn", "New", "Breadth", "Rework", "Types")

# A repo must have had at least this many commits in the prior window
# for its slowdown to be worth narrating as a "cooler".
COOLER_PRIOR_FLOOR = 10


@dataclass
class RepoWeek:
    """One repo's rolling-7-day snapshot (merges excluded throughout)."""

    name: str
    path: str
    commits: int = 0             # commits in the window
    prior_commits: int = 0       # commits in the 7 days before the window
    insertions: int = 0
    deletions: int = 0
    new_files: int = 0           # files added (--diff-filter=A), deduped
    files_changed: int = 0       # distinct paths touched
    file_types: int = 0          # distinct extensions among touched paths
    dirty: bool = False          # uncommitted changes right now
    lifetime_commits: int = 0    # whole-history size (quiet-strip chip)
    first_commit_ts: int | None = None
    last_commit_ts: int | None = None   # newest commit within the trend span
    new_from_zero: bool = False  # repo's first commit landed in the window
    release: str | None = None   # newest tag, if it was created in the window
    release_ts: int | None = None

    @property
    def churn(self) -> int:
        return self.insertions + self.deletions

    @property
    def net(self) -> int:
        return self.insertions - self.deletions

    @property
    def delta(self) -> int:
        return self.commits - self.prior_commits

    @property
    def lines_per_commit(self) -> int:
        return round(self.churn / self.commits) if self.commits else 0


@dataclass
class RepoStats:
    active: list[RepoWeek] = field(default_factory=list)   # newest activity first
    quiet: list[RepoWeek] = field(default_factory=list)    # biggest lifetime first
    # Commits per trailing week across all repos, oldest week first;
    # [-1] is the current rolling window. Always length TREND_WEEKS.
    weekly_totals: list[int] = field(default_factory=lambda: [0] * TREND_WEEKS)
    gathered_ts: int = 0         # freshness stamp (epoch secs of the sweep)

    @property
    def repo_count(self) -> int:
        return len(self.active) + len(self.quiet)

    @property
    def week_total(self) -> int:
        return sum(r.commits for r in self.active)

    @property
    def four_week_avg(self) -> float:
        """Mean commits/week over the four full weeks before this one."""
        prior = self.weekly_totals[-5:-1]
        return sum(prior) / len(prior) if prior else 0.0

    @property
    def total_insertions(self) -> int:
        return sum(r.insertions for r in self.active)

    @property
    def total_deletions(self) -> int:
        return sum(r.deletions for r in self.active)

    @property
    def total_new_files(self) -> int:
        return sum(r.new_files for r in self.active)

    @property
    def releases(self) -> list[RepoWeek]:
        return [r for r in self.active + self.quiet if r.release]


def _run_git(path: str | os.PathLike[str], args: list[str], timeout: int = 3) -> str | None:
    """Run `git -C path <args>`; return stdout, or None on any failure.

    Mirrors `repo_store`'s git helpers. A None return means "skip this
    value" — the caller never distinguishes the failure modes."""
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


def _final_path(p: str) -> str:
    """Resolve git's rename notation to the post-rename path.

    Handles both `dir/{old => new}/f.py` and bare `old.py => new.py`."""
    if "{" in p and "=>" in p:
        pre, _, rest = p.partition("{")
        inner, _, post = rest.partition("}")
        new = inner.split("=>")[-1].strip()
        return (pre + new + post).replace("//", "/")
    if " => " in p:
        return p.split(" => ")[-1]
    return p


def _ext(p: str) -> str:
    base = p.rsplit("/", 1)[-1]
    # A leading dot (".gitignore") is a bare name, not an extension.
    if "." in base[1:]:
        return base.rsplit(".", 1)[-1].lower()
    return ""


def _int_or_none(token: str) -> int | None:
    try:
        v = int(token)
        datetime.fromtimestamp(v)   # reject out-of-range stamps
        return v
    except (ValueError, OverflowError, OSError):
        return None


def gather_stats(repos: Iterable[tuple[str, str]], now: datetime | None = None) -> RepoStats:
    """Aggregate git stats over `repos`, an iterable of (path, display_name).

    Dedups by real path so duplicate sidebar rows sharing one path don't
    double-count. `now` defaults to the local current time and anchors
    every rolling window."""
    now = now or datetime.now()
    now_ts = int(now.timestamp())
    since_7d = (now - timedelta(days=ROLL_DAYS)).isoformat(sep=" ", timespec="seconds")
    since_trend = (now - timedelta(days=ROLL_DAYS * TREND_WEEKS)).isoformat(
        sep=" ", timespec="seconds")
    window_start_ts = now_ts - _WEEK_SECS

    stats = RepoStats(gathered_ts=now_ts)
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
        rw = RepoWeek(name=name, path=str(path), dirty=bool(status.strip()))

        # Window commits + churn + breadth in one pass: each commit is a
        # \x01-marked stamp line followed by its numstat rows.
        out = _run_git(path, ["log", "--no-merges", f"--since={since_7d}",
                              "--numstat", "--format=%x01%ct"])
        touched: set[str] = set()
        for line in (out or "").splitlines():
            if line.startswith("\x01"):
                rw.commits += 1
                # git %ct is external input — a malformed or out-of-range
                # value must be skipped, not raise, so this stays the
                # documented "never raises on a bad repo" boundary.
                ts = _int_or_none(line[1:])
                if ts is not None and (rw.last_commit_ts is None or ts > rw.last_commit_ts):
                    rw.last_commit_ts = ts
            elif "\t" in line:
                ins_s, del_s, p = line.split("\t", 2)
                touched.add(_final_path(p))
                # binary files numstat as "-\t-" — churn unknown, still counted
                if ins_s.isdigit():
                    rw.insertions += int(ins_s)
                if del_s.isdigit():
                    rw.deletions += int(del_s)
        rw.files_changed = len(touched)
        rw.file_types = len({_ext(p) for p in touched})

        out = _run_git(path, ["log", "--no-merges", f"--since={since_7d}",
                              "--diff-filter=A", "--name-only", "--format="])
        rw.new_files = len({l for l in (out or "").splitlines() if l.strip()})

        # One trend sweep yields the prior-window count AND the 8-week
        # histogram, bucketed by exact 7-day spans back from `now`.
        out = _run_git(path, ["log", "--no-merges", f"--since={since_trend}",
                              "--format=%ct"])
        for token in (out or "").split():
            ts = _int_or_none(token)
            if ts is None:
                continue
            bucket = (now_ts - ts) // _WEEK_SECS
            if 0 <= bucket < TREND_WEEKS:
                stats.weekly_totals[TREND_WEEKS - 1 - bucket] += 1
            if bucket == 1:
                rw.prior_commits += 1

        out = _run_git(path, ["rev-list", "--count", "--no-merges", "HEAD"])
        if out and out.strip().isdigit():
            rw.lifetime_commits = int(out.strip())

        out = _run_git(path, ["log", "--max-parents=0", "--format=%ct"])
        roots = [t for t in (out or "").split() if _int_or_none(t) is not None]
        if roots:
            rw.first_commit_ts = min(int(t) for t in roots)
            rw.new_from_zero = rw.first_commit_ts >= window_start_ts

        out = _run_git(path, ["for-each-ref", "refs/tags", "--sort=-creatordate",
                              "--count=1", "--format=%(creatordate:unix)%00%(refname:short)"])
        if out and "\x00" in out:
            ts_s, tag = out.strip().split("\x00", 1)
            ts = _int_or_none(ts_s)
            if ts is not None and ts >= window_start_ts and tag:
                rw.release = tag
                rw.release_ts = ts

        (stats.active if rw.commits else stats.quiet).append(rw)

    stats.active.sort(key=lambda r: r.last_commit_ts or 0, reverse=True)
    stats.quiet.sort(key=lambda r: r.lifetime_commits, reverse=True)
    return stats


def churn_tag(r: RepoWeek) -> str:
    """Coarse read of the week's churn shape, from the insertion share."""
    if not r.churn:
        return "balanced"
    share = r.insertions / r.churn
    if share >= 0.90:
        return "mostly new work"
    if share >= 0.60:
        return "growing"
    if share <= 0.40:
        return "trimming"
    return "balanced"


def fingerprints(active: list[RepoWeek]) -> dict[str, tuple[float, ...]]:
    """0..1 radar spoke values per repo path (axes = RADAR_AXES).

    Each axis is normalized to the busiest active repo this window, so
    the silhouettes compare. Rework is deletions' share of churn — a
    0..1 ratio like the others only after the same per-axis max scaling."""
    def axes(r: RepoWeek) -> tuple[float, ...]:
        rework = (r.deletions / r.churn) if r.churn else 0.0
        return (r.commits, r.churn, r.new_files, r.files_changed, rework, r.file_types)

    raw = {r.path: axes(r) for r in active}
    maxima = [max((v[i] for v in raw.values()), default=0.0) for i in range(len(RADAR_AXES))]
    return {
        p: tuple((v[i] / maxima[i]) if maxima[i] else 0.0 for i in range(len(RADAR_AXES)))
        for p, v in raw.items()
    }


# ── narrative (deterministic template NLG — no LLM) ──
#
# Each clause draws from a small phrasing pool indexed by ISO week number,
# so the sentence varies week-over-week yet stays deterministic/testable.

_TONE_GROWING = ("A growing week.", "A big week.", "Momentum this week.")
_TONE_STEADY = ("A steady week.", "An even week.", "A consistent week.")
_TONE_QUIET = ("A quieter week.", "An easing week.", "A calmer week.")
_TONE_IDLE = ("A quiet week — nothing landed.", "All quiet this week.",
              "No commits this week.")
_SHIP_VERBS = ("shipped", "released", "cut")
_KICKOFF_VERBS = ("kicked off from zero", "started from nothing", "sprang to life")
_GROWER_VERBS = ("picked up the pace", "stepped up", "accelerated")
_COOLER_VERBS = ("eased off after big prior weeks", "wound down after a big stretch",
                 "took a breather")

# week_total / four_week_avg thresholds for the tone clause.
_GROWING_RATIO = 1.15
_QUIET_RATIO = 0.85


def _fmt_lines(n: int) -> str:
    return f"+{round(n / 1000)}k" if n >= 1000 else f"+{n}"


def summarize(stats: RepoStats, now: datetime | None = None,
              release_color: str = "#859900") -> str:
    """One-sentence-ish HTML narrative: tone, standouts, coolers.

    Standout priority: released > new-from-zero > biggest grower (at most
    two standouts). Coolers are repos whose commits dropped vs a prior
    week of at least COOLER_PRIOR_FLOOR. Output uses <b> and a colored
    <span> for the release clause; repo names are HTML-escaped."""
    now = now or datetime.now()
    week = now.isocalendar()[1]

    def pick(pool: tuple[str, ...]) -> str:
        return pool[week % len(pool)]

    total = stats.week_total
    if total == 0:
        return pick(_TONE_IDLE)

    avg = stats.four_week_avg
    if avg <= 0 or total / avg >= _GROWING_RATIO:
        tone = pick(_TONE_GROWING)
    elif total / avg <= _QUIET_RATIO:
        tone = pick(_TONE_QUIET)
    else:
        tone = pick(_TONE_STEADY)
    parts = [tone]

    mentioned: set[str] = set()
    standouts: list[str] = []

    def esc(r: RepoWeek) -> str:
        return html.escape(r.name)

    for r in sorted(stats.releases, key=lambda r: r.release_ts or 0, reverse=True):
        if len(standouts) >= 2:
            break
        mentioned.add(r.path)
        standouts.append(
            f'<span style="color:{release_color}"><b>{esc(r)}</b> '
            f'{pick(_SHIP_VERBS)} {html.escape(r.release or "")}</span>')
    for r in sorted((r for r in stats.active if r.new_from_zero and r.path not in mentioned),
                    key=lambda r: r.commits, reverse=True):
        if len(standouts) >= 2:
            break
        mentioned.add(r.path)
        standouts.append(
            f"<b>{esc(r)}</b> {pick(_KICKOFF_VERBS)} — {r.commits} commits, "
            f"{_fmt_lines(r.insertions)} lines")
    growers = sorted((r for r in stats.active if r.delta > 0 and r.path not in mentioned),
                     key=lambda r: r.delta, reverse=True)
    if growers and len(standouts) < 2:
        r = growers[0]
        mentioned.add(r.path)
        standouts.append(f"<b>{esc(r)}</b> {pick(_GROWER_VERBS)} (+{r.delta} commits)")

    if standouts:
        parts.append(" and ".join(standouts) + ".")

    coolers = sorted(
        (r for r in stats.active
         if r.delta < 0 and r.prior_commits >= COOLER_PRIOR_FLOOR
         and r.path not in mentioned),
        key=lambda r: r.delta)[:2]
    if coolers:
        names = " and ".join(f"<b>{esc(r)}</b>" for r in coolers)
        parts.append(f"{names} {pick(_COOLER_VERBS)}.")

    return " ".join(parts)


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
