"""The dashboard groups rows by repository: the main checkout and its linked
worktrees get one card with the main name and the badge of the main
checkout's row, and a commit that two folders share counts one time.
Spec: `docs/specs/worktree.md` section 8."""

from __future__ import annotations

import os
from pathlib import Path

import src.core.repo_stats as repo_stats
from src.core.repo_stats import gather_stats
from src.core.repo_store import Repo
from tests.gitrepo import git, seed
from tests.test_repo_stats import NOW, _commit, _iso


def _repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    main = Path(os.path.realpath(tmp_path)) / "proj"
    seed(main)
    _commit(main, "a.py", "shared", _iso(2))
    wt = main.parent / "proj-fix-a"
    git("-C", str(main), "worktree", "add", "-q", "-b", "fix/a", str(wt))
    _commit(wt, "b.py", "only in the worktree", _iso(1))
    return main, wt


def test_two_worktree_rows_make_one_card_and_a_shared_commit_counts_once(tmp_path: Path) -> None:
    main, wt = _repo_with_worktree(tmp_path)
    stats = gather_stats([Repo(path=str(main), emoji="🌱"), Repo(path=str(wt), emoji="🔧")], now=NOW)
    assert [r.name for r in stats.active] == ["🌱 proj"]
    card = stats.active[0]
    assert card.worktrees == 1
    assert card.commits == 2
    assert card.lifetime_commits == 2
    assert card.files_changed == 2
    assert sum(stats.weekly_totals) == 2
    assert stats.quiet == []


def test_the_card_is_dirty_when_any_folder_is_dirty(tmp_path: Path) -> None:
    main, wt = _repo_with_worktree(tmp_path)
    (wt / "b.py").write_text("edited\n")
    stats = gather_stats([Repo(path=str(main)), Repo(path=str(wt))], now=NOW)
    assert stats.active[0].dirty is True


def test_a_lone_worktree_row_takes_the_main_name(tmp_path: Path) -> None:
    _, wt = _repo_with_worktree(tmp_path)
    stats = gather_stats([Repo(path=str(wt), emoji="🔧")], now=NOW)
    assert [r.name for r in stats.active] == ["🔧 proj"]
    assert stats.active[0].commits == 2
    assert stats.active[0].worktrees == 1


def test_a_main_checkout_alone_keeps_its_row_name(tmp_path: Path) -> None:
    main, _ = _repo_with_worktree(tmp_path)
    stats = gather_stats([Repo(path=str(main), emoji="🌱", instance=1)], now=NOW)
    assert [r.name for r in stats.active] == ["🌱 proj (I)"]
    assert stats.active[0].commits == 1
    assert stats.active[0].worktrees == 0


def test_two_repositories_keep_two_cards(tmp_path: Path) -> None:
    main, wt = _repo_with_worktree(tmp_path)
    other = Path(os.path.realpath(tmp_path)) / "other"
    seed(other)
    _commit(other, "c.py", "other", _iso(1))
    stats = gather_stats([Repo(path=str(main)), Repo(path=str(other)), Repo(path=str(wt))], now=NOW)
    assert sorted((r.name, r.commits) for r in stats.active) == [("other", 1), ("proj", 2)]


def test_old_git_with_no_common_dir_keeps_a_card_per_folder(tmp_path: Path, monkeypatch) -> None:
    main, wt = _repo_with_worktree(tmp_path)
    monkeypatch.setattr(repo_stats, "git_common_dir", lambda path: None)
    monkeypatch.setattr(repo_stats, "worktree_main_name", lambda path: "")
    stats = gather_stats([Repo(path=str(main)), Repo(path=str(wt))], now=NOW)
    assert sorted((r.name, r.commits) for r in stats.active) == [("proj", 1), ("proj-fix-a", 2)]


def test_a_folder_outside_git_is_skipped(tmp_path: Path) -> None:
    plain = Path(os.path.realpath(tmp_path)) / "plain"
    plain.mkdir()
    assert gather_stats([Repo(path=str(plain))], now=NOW).repo_count == 0


def test_the_main_checkout_row_gives_the_badge_even_when_it_has_none(tmp_path: Path) -> None:
    main, wt = _repo_with_worktree(tmp_path)
    stats = gather_stats([Repo(path=str(wt), emoji="🔧"), Repo(path=str(main))], now=NOW)
    assert [r.name for r in stats.active] == ["proj"]


def test_the_card_counts_each_linked_worktree_once(tmp_path: Path) -> None:
    main, wt = _repo_with_worktree(tmp_path)
    wt2 = main.parent / "proj-fix-b"
    git("-C", str(main), "worktree", "add", "-q", "-b", "fix/b", str(wt2))
    rows = [Repo(path=str(main), emoji="🌱"), Repo(path=str(wt)), Repo(path=str(wt), instance=2),
            Repo(path=str(wt2))]
    assert gather_stats(rows, now=NOW).active[0].worktrees == 2
