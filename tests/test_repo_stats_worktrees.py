"""The dashboard groups rows by repository: the main checkout and its linked
worktrees get one card with the main name, and a commit that two folders
share counts one time. Spec: `docs/specs/worktree.md` section 8."""

from __future__ import annotations

import os
from pathlib import Path

import src.core.repo_stats as repo_stats
from src.core.repo_stats import gather_stats
from tests.test_repo_stats import NOW, _commit, _git, _iso, _make_repo


def _repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    main = Path(os.path.realpath(tmp_path)) / "proj"
    _make_repo(main)
    _commit(main, "a.py", "shared", _iso(2))
    wt = main.parent / "proj-fix-a"
    _git(main, "worktree", "add", "-q", "-b", "fix/a", str(wt))
    _commit(wt, "b.py", "only in the worktree", _iso(1))
    return main, wt


def test_two_worktree_rows_make_one_card_and_a_shared_commit_counts_once(tmp_path: Path) -> None:
    main, wt = _repo_with_worktree(tmp_path)
    stats = gather_stats([(str(main), "🌱 proj"), (str(wt), "proj-fix-a")], now=NOW)
    assert [r.name for r in stats.active] == ["proj"]
    card = stats.active[0]
    assert card.commits == 2
    assert card.lifetime_commits == 2
    assert card.files_changed == 2
    assert sum(stats.weekly_totals) == 2
    assert stats.quiet == []


def test_the_card_is_dirty_when_any_folder_is_dirty(tmp_path: Path) -> None:
    main, wt = _repo_with_worktree(tmp_path)
    (wt / "b.py").write_text("edited\n")
    stats = gather_stats([(str(main), "proj"), (str(wt), "proj-fix-a")], now=NOW)
    assert stats.active[0].dirty is True


def test_a_lone_worktree_row_takes_the_main_name(tmp_path: Path) -> None:
    _, wt = _repo_with_worktree(tmp_path)
    stats = gather_stats([(str(wt), "proj-fix-a")], now=NOW)
    assert [r.name for r in stats.active] == ["proj"]
    assert stats.active[0].commits == 2


def test_a_main_checkout_alone_keeps_its_row_name(tmp_path: Path) -> None:
    main, _ = _repo_with_worktree(tmp_path)
    stats = gather_stats([(str(main), "🌱 proj (I)")], now=NOW)
    assert [r.name for r in stats.active] == ["🌱 proj (I)"]
    assert stats.active[0].commits == 1


def test_two_repositories_keep_two_cards(tmp_path: Path) -> None:
    main, wt = _repo_with_worktree(tmp_path)
    other = Path(os.path.realpath(tmp_path)) / "other"
    _make_repo(other)
    _commit(other, "c.py", "other", _iso(1))
    stats = gather_stats([(str(main), "proj"), (str(other), "other"), (str(wt), "proj-fix-a")], now=NOW)
    assert sorted((r.name, r.commits) for r in stats.active) == [("other", 1), ("proj", 2)]


def test_old_git_with_no_common_dir_keeps_a_card_per_folder(tmp_path: Path, monkeypatch) -> None:
    main, wt = _repo_with_worktree(tmp_path)
    monkeypatch.setattr(repo_stats, "git_common_dir", lambda path: None)
    monkeypatch.setattr(repo_stats, "worktree_main_name", lambda path: "")
    stats = gather_stats([(str(main), "proj"), (str(wt), "proj-fix-a")], now=NOW)
    assert sorted((r.name, r.commits) for r in stats.active) == [("proj", 1), ("proj-fix-a", 2)]


def test_a_folder_outside_git_is_skipped(tmp_path: Path) -> None:
    plain = Path(os.path.realpath(tmp_path)) / "plain"
    plain.mkdir()
    assert gather_stats([(str(plain), "plain")], now=NOW).repo_count == 0
