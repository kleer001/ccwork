"""Remove from sidebar on a worktree row: an opt-in delete of the folder and
its branch, after the dialog lists the ignored files that go with them.
Spec: `docs/specs/worktree.md` section 7."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QMessageBox

from src.core.repo_store import Repo, RepoStore
from src.core.worktree import (
    GitError, has_submodules, ignored_entries, make_worktree, remove_worktree,
    worktree_plan, worktree_source,
)
from src.ui.repo_sidebar import RepoSidebar
from src.ui.worktree_dialog import WorktreeRemoveDialog


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, msg: str) -> None:
    _git("-C", str(repo), "add", "-A")
    _git("-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    repo = Path(os.path.realpath(tmp_path)) / "proj"
    _git("init", "-q", "-b", "main", str(repo))
    (repo / "README").write_text("seed\n")
    (repo / ".gitignore").write_text(".env\ntmp/\n")
    _commit(repo, "seed")
    return repo


@pytest.fixture
def wt(main_repo: Path) -> Path:
    folder = make_worktree(worktree_plan(worktree_source(str(main_repo)), "fix/a"))
    return Path(folder)


def _branches(repo: Path) -> list[str]:
    return _git("-C", str(repo), "branch", "--format=%(refname:short)").split()


# ── core ──

def test_ignored_entries_lists_files_and_whole_folders(wt: Path) -> None:
    (wt / ".env").write_text("KEY=1\n")
    (wt / "tmp").mkdir()
    (wt / "tmp" / "result.csv").write_text("1\n")
    assert sorted(ignored_entries(str(wt))) == [".env", "tmp/"]


def test_remove_deletes_a_clean_worktree_and_its_branch(main_repo: Path, wt: Path) -> None:
    (wt / ".env").write_text("KEY=1\n")
    assert remove_worktree(str(wt), "fix/a") == ""
    assert not wt.exists()
    assert "fix/a" not in _branches(main_repo)


def test_remove_refuses_a_dirty_worktree(main_repo: Path, wt: Path) -> None:
    (wt / "README").write_text("edited\n")
    with pytest.raises(GitError, match="modified or untracked"):
        remove_worktree(str(wt), "fix/a")
    assert wt.exists()
    assert "fix/a" in _branches(main_repo)


def test_remove_keeps_an_unmerged_branch(main_repo: Path, wt: Path) -> None:
    (wt / "new.txt").write_text("work\n")
    _commit(wt, "work")
    note = remove_worktree(str(wt), "fix/a")
    assert not wt.exists()
    assert "fix/a" in _branches(main_repo)
    assert note == ("The folder is deleted. The branch fix/a stays, because it has "
                    "commits that are not merged.")


def test_submodules_are_detected(main_repo: Path, tmp_path: Path) -> None:
    lib = Path(os.path.realpath(tmp_path)) / "lib"
    _git("init", "-q", "-b", "main", str(lib))
    (lib / "x").write_text("x\n")
    _commit(lib, "lib")
    _git("-C", str(main_repo), "-c", "protocol.file.allow=always", "submodule", "add", "-q",
         str(lib), "lib")
    _commit(main_repo, "add lib")
    folder = make_worktree(worktree_plan(worktree_source(str(main_repo)), "sub"))
    assert has_submodules(folder) is True
    assert has_submodules(str(main_repo)) is True


def test_no_submodules(wt: Path) -> None:
    assert has_submodules(str(wt)) is False


# ── dialog ──

def _box(dlg: WorktreeRemoveDialog) -> QCheckBox:
    return dlg.findChild(QCheckBox)


def _texts(dlg) -> str:
    return " ".join(l.text() for l in dlg.findChildren(QLabel))


def test_dialog_box_is_off_and_lists_ignored_entries(qapp: QApplication, wt: Path) -> None:
    (wt / ".env").write_text("KEY=1\n")
    dlg = WorktreeRemoveDialog(str(wt))
    assert _box(dlg).isEnabled() and not _box(dlg).isChecked()
    assert "These ignored files and folders are deleted too:" in _texts(dlg)
    assert ".env" in _texts(dlg)


def test_dialog_lists_ten_names_and_the_count_of_the_rest(qapp: QApplication, wt: Path) -> None:
    for i in range(13):
        (wt / f"f{i:02}.env").write_text("x\n")
    (wt / ".gitignore").write_text(".env\ntmp/\n*.env\n")
    _commit(wt, "ignore more")
    dlg = WorktreeRemoveDialog(str(wt))
    assert "f09.env" in _texts(dlg) and "f10.env" not in _texts(dlg)
    assert "and 3 more" in _texts(dlg)


def test_dialog_hides_the_list_with_no_ignored_entries(qapp: QApplication, wt: Path) -> None:
    dlg = WorktreeRemoveDialog(str(wt))
    assert "deleted too" not in _texts(dlg)


def test_dialog_box_is_disabled_with_the_reason(qapp: QApplication, wt: Path) -> None:
    dlg = WorktreeRemoveDialog(str(wt), blocked="Another row uses this folder.")
    assert not _box(dlg).isEnabled() and not _box(dlg).isChecked()
    assert "Another row uses this folder." in _texts(dlg)


def test_dialog_box_is_disabled_for_a_worktree_with_submodules(
    qapp: QApplication, main_repo: Path, tmp_path: Path
) -> None:
    lib = Path(os.path.realpath(tmp_path)) / "lib"
    _git("init", "-q", "-b", "main", str(lib))
    (lib / "x").write_text("x\n")
    _commit(lib, "lib")
    _git("-C", str(main_repo), "-c", "protocol.file.allow=always", "submodule", "add", "-q",
         str(lib), "lib")
    _commit(main_repo, "add lib")
    folder = make_worktree(worktree_plan(worktree_source(str(main_repo)), "sub"))
    dlg = WorktreeRemoveDialog(folder)
    assert not _box(dlg).isEnabled() and not _box(dlg).isChecked()
    assert "The worktree has submodules. Git does not delete it." in _texts(dlg)


# ── sidebar flow ──

def _sidebar(tmp_path: Path, paths: list[str]) -> RepoSidebar:
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path=p) for p in paths]
    store.save()
    sidebar = RepoSidebar(store)
    sidebar.refresh_branches()
    return sidebar


def _answer(monkeypatch, delete: bool, accept: bool = True) -> None:
    def exec_(self):
        _box(self).setChecked(delete)
        return int(accept)
    monkeypatch.setattr(WorktreeRemoveDialog, "exec", exec_)


def test_box_on_deletes_folder_and_branch_and_skips_recent(
    qapp: QApplication, tmp_path: Path, main_repo: Path, wt: Path, monkeypatch
) -> None:
    sidebar = _sidebar(tmp_path, [str(main_repo), str(wt)])
    _answer(monkeypatch, delete=True)
    sidebar._confirm_remove(sidebar.model.repo_at(1), 1)
    assert [r.path for r in sidebar.model._store.repos] == [str(main_repo)]
    assert not wt.exists()
    assert "fix/a" not in _branches(main_repo)
    assert sidebar.model._store.recent == []


def test_box_off_keeps_folder_and_branch_and_goes_to_recent(
    qapp: QApplication, tmp_path: Path, main_repo: Path, wt: Path, monkeypatch
) -> None:
    sidebar = _sidebar(tmp_path, [str(main_repo), str(wt)])
    _answer(monkeypatch, delete=False)
    sidebar._confirm_remove(sidebar.model.repo_at(1), 1)
    assert len(sidebar.model._store.repos) == 1
    assert wt.exists() and "fix/a" in _branches(main_repo)
    assert [e["path"] for e in sidebar.model._store.recent] == [str(wt)]


def test_git_refusal_shows_the_message_and_keeps_the_row(
    qapp: QApplication, tmp_path: Path, main_repo: Path, wt: Path, monkeypatch
) -> None:
    (wt / "README").write_text("edited\n")
    sidebar = _sidebar(tmp_path, [str(main_repo), str(wt)])
    _answer(monkeypatch, delete=True)
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    sidebar._confirm_remove(sidebar.model.repo_at(1), 1)
    assert len(sidebar.model._store.repos) == 2
    assert wt.exists()
    assert shown and "modified or untracked" in shown[0]


def test_unmerged_branch_note_is_shown_and_the_row_goes(
    qapp: QApplication, tmp_path: Path, main_repo: Path, wt: Path, monkeypatch
) -> None:
    (wt / "new.txt").write_text("work\n")
    _commit(wt, "work")
    sidebar = _sidebar(tmp_path, [str(main_repo), str(wt)])
    _answer(monkeypatch, delete=True)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    sidebar._confirm_remove(sidebar.model.repo_at(1), 1)
    assert len(sidebar.model._store.repos) == 1
    assert shown and "stays, because it has commits that are not merged" in shown[0]


def test_main_checkout_row_keeps_the_plain_question(
    qapp: QApplication, tmp_path: Path, main_repo: Path, monkeypatch
) -> None:
    sidebar = _sidebar(tmp_path, [str(main_repo)])
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: (asked.append(a[1]), QMessageBox.No)[1])
    monkeypatch.setattr(WorktreeRemoveDialog, "exec", lambda self: pytest.fail("worktree dialog"))
    sidebar._confirm_remove(sidebar.model.repo_at(0), 0)
    assert asked == ["Remove from sidebar"]
    assert len(sidebar.model._store.repos) == 1


def test_two_rows_on_the_folder_block_the_delete(
    qapp: QApplication, tmp_path: Path, main_repo: Path, wt: Path, monkeypatch
) -> None:
    sidebar = _sidebar(tmp_path, [str(wt), str(wt)])
    seen = []
    monkeypatch.setattr(WorktreeRemoveDialog, "exec", lambda self: (seen.append(_box(self).isEnabled()), 0)[1])
    sidebar._confirm_remove(sidebar.model.repo_at(0), 0)
    assert seen == [False]


def test_a_live_claude_session_blocks_the_delete(
    qapp: QApplication, tmp_path: Path, main_repo: Path, wt: Path, monkeypatch
) -> None:
    sidebar = _sidebar(tmp_path, [str(wt)])
    repo = sidebar.model.repo_at(0)
    sidebar.set_terminal_active(repo.id, True)
    sidebar.apply_hook_event("SessionStart", repo.id, {"session_id": "s1"})
    texts = []
    monkeypatch.setattr(WorktreeRemoveDialog, "exec", lambda self: (texts.append(_texts(self)), 0)[1])
    sidebar._confirm_remove(repo, 0)
    assert texts and "Claude runs in this row." in texts[0]


def test_the_branch_comes_from_git_not_the_row_cache(
    qapp: QApplication, tmp_path: Path, main_repo: Path, wt: Path, monkeypatch
) -> None:
    sidebar = _sidebar(tmp_path, [str(main_repo), str(wt)])
    _git("-C", str(wt), "switch", "-q", "-c", "fix/b")
    _answer(monkeypatch, delete=True)
    sidebar._confirm_remove(sidebar.model.repo_at(1), 1)
    assert "fix/b" not in _branches(main_repo)
    assert "fix/a" in _branches(main_repo)


def test_a_branch_used_elsewhere_stays_with_a_note(main_repo: Path, wt: Path) -> None:
    other = main_repo.parent / "other"
    _git("-C", str(main_repo), "worktree", "add", "-q", "-b", "o", str(other))
    _git("-C", str(other), "checkout", "-q", "--detach")
    _git("-C", str(wt), "checkout", "-q", "--detach")
    _git("-C", str(other), "checkout", "-q", "fix/a")
    note = remove_worktree(str(wt), "fix/a")
    assert not wt.exists()
    assert note.startswith("The folder is deleted. The branch fix/a stays: ")


def test_a_locked_worktree_refusal_names_the_unlock_command(main_repo: Path, wt: Path) -> None:
    _git("-C", str(main_repo), "worktree", "lock", "--reason", "claude session", str(wt))
    with pytest.raises(GitError) as e:
        remove_worktree(str(wt), "fix/a")
    assert "locked" in str(e.value)
    assert str(e.value).endswith(f"If no session uses it, run: git worktree unlock {wt}")
    assert wt.exists()
