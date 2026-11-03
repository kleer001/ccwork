"""Make worktree…: the plan the dialog shows, the git calls, the new row.
Spec: `docs/specs/worktree.md` 5.1 to 5.3."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLabel, QLineEdit, QMessageBox

from src.core.repo_store import Repo, RepoStore
from src.core.worktree import GitError, make_worktree, worktree_plan, worktree_source
from src.ui.repo_model import ROLE_WORKTREE_OF
from src.ui.repo_sidebar import RepoSidebar
from src.ui.worktree_dialog import WorktreeDialog


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    repo = Path(os.path.realpath(tmp_path)) / "proj"
    _git("init", "-q", "-b", "main", str(repo))
    (repo / "README").write_text("seed\n")
    _git("-C", str(repo), "add", "README")
    _git("-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
    return repo


# ── plan ──

def test_plan_for_a_clean_main_row(main_repo: Path) -> None:
    plan = worktree_plan(worktree_source(str(main_repo)), "fix/a")
    assert plan.folder == str(main_repo.parent / "proj-fix-a")
    assert plan.name == "fix/a"
    assert plan.source.base == "main"
    assert plan.source.commit == _git("-C", str(main_repo), "rev-parse", "--short", "HEAD")
    assert plan.source.dirty is False
    assert plan.problem == ""


@pytest.mark.parametrize("name, problem", [
    ("", "Type a name for the branch."),
    ("bad..name", "Git does not accept this branch name."),
    ("@{-1}", "Git does not accept this branch name."),
])
def test_plan_refuses_bad_names(main_repo: Path, name: str, problem: str) -> None:
    assert worktree_plan(worktree_source(str(main_repo)), name).problem == problem


def test_plan_refuses_an_existing_branch(main_repo: Path) -> None:
    _git("-C", str(main_repo), "branch", "taken")
    assert worktree_plan(worktree_source(str(main_repo)), "taken").problem == "The branch taken exists."


def test_plan_refuses_an_existing_folder(main_repo: Path) -> None:
    (main_repo.parent / "proj-here").mkdir()
    plan = worktree_plan(worktree_source(str(main_repo)), "here")
    assert plan.problem == f"The folder {main_repo.parent / 'proj-here'} exists."


def test_plan_from_a_detached_head(main_repo: Path) -> None:
    _git("-C", str(main_repo), "checkout", "-q", "--detach")
    plan = worktree_plan(worktree_source(str(main_repo)), "x")
    assert plan.source.base is None
    assert plan.problem == ""


def test_plan_sees_uncommitted_changes(main_repo: Path) -> None:
    (main_repo / "README").write_text("edited\n")
    assert worktree_plan(worktree_source(str(main_repo)), "x").source.dirty is True


def test_plan_from_a_worktree_row_uses_the_main_name(main_repo: Path) -> None:
    first = make_worktree(worktree_plan(worktree_source(str(main_repo)), "one"))
    plan = worktree_plan(worktree_source(first), "two")
    assert plan.folder == str(main_repo.parent / "proj-two")
    assert plan.source.base == "one"


# ── git ──

def test_make_worktree_adds_folder_branch_and_base(main_repo: Path) -> None:
    folder = make_worktree(worktree_plan(worktree_source(str(main_repo)), "fix/a"))
    assert folder == str(main_repo.parent / "proj-fix-a")
    assert _git("-C", folder, "branch", "--show-current") == "fix/a"
    assert _git("-C", folder, "config", "branch.fix/a.ccworkBase") == "main"


def test_make_worktree_from_detached_head_sets_no_base(main_repo: Path) -> None:
    _git("-C", str(main_repo), "checkout", "-q", "--detach")
    folder = make_worktree(worktree_plan(worktree_source(str(main_repo)), "x"))
    r = subprocess.run(["git", "-C", folder, "config", "branch.x.ccworkBase"], capture_output=True)
    assert r.returncode == 1


def test_make_worktree_leaves_uncommitted_changes_in_the_source(main_repo: Path) -> None:
    (main_repo / "README").write_text("edited\n")
    folder = make_worktree(worktree_plan(worktree_source(str(main_repo)), "x"))
    assert (Path(folder) / "README").read_text() == "seed\n"
    assert (main_repo / "README").read_text() == "edited\n"


def test_make_worktree_raises_with_git_message(main_repo: Path) -> None:
    plan = worktree_plan(worktree_source(str(main_repo)), "late")
    _git("-C", str(main_repo), "branch", "late")
    with pytest.raises(GitError, match="already exists"):
        make_worktree(plan)
    assert not Path(plan.folder).exists()


# ── menu and dialog ──

def _sidebar(tmp_path: Path, paths: list[str]) -> RepoSidebar:
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path=p) for p in paths]
    store.save()
    sidebar = RepoSidebar(store)
    sidebar.refresh_branches()
    return sidebar


def _labels(sidebar: RepoSidebar, row: int) -> list[str]:
    return [a.text() for a in sidebar._build_context_menu(sidebar.model.repo_at(row), row).actions()]


def _action(sidebar: RepoSidebar, row: int, text: str):
    menu = sidebar._build_context_menu(sidebar.model.repo_at(row), row)
    return next(a for a in menu.actions() if a.text() == text)


def test_menu_item_sits_below_clone(qapp: QApplication, tmp_path: Path, main_repo: Path) -> None:
    sidebar = _sidebar(tmp_path, [str(main_repo)])
    labels = _labels(sidebar, 0)
    assert labels[labels.index("Clone this repo") + 1] == "Make worktree…"
    assert _action(sidebar, 0, "Make worktree…").isEnabled()


def test_menu_item_is_off_for_a_missing_or_non_git_folder(
    qapp: QApplication, tmp_path: Path
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    sidebar = _sidebar(tmp_path, [str(plain), str(tmp_path / "gone")])
    assert not _action(sidebar, 0, "Make worktree…").isEnabled()
    assert not _action(sidebar, 1, "Make worktree…").isEnabled()


def _dialog_state(dlg: WorktreeDialog) -> tuple[bool, str]:
    ok = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
    return ok.isEnabled(), dlg._problem.text()


def test_dialog_keeps_ok_off_with_the_reason(
    qapp: QApplication, tmp_path: Path, main_repo: Path
) -> None:
    _git("-C", str(main_repo), "branch", "taken")
    (main_repo.parent / "proj-here").mkdir()
    dlg = WorktreeDialog(str(main_repo))
    field = dlg.findChild(QLineEdit)
    for name in ("", "bad..name", "@{-1}", "taken", "here"):
        field.setText(name)
        enabled, reason = _dialog_state(dlg)
        assert not enabled and reason, name
    field.setText("fix/a")
    assert _dialog_state(dlg) == (True, "")
    texts = " ".join(l.text() for l in dlg.findChildren(QLabel))
    assert str(main_repo.parent / "proj-fix-a") in texts
    assert "from main at" in texts
    assert "Uncommitted changes" not in texts


def test_dialog_names_uncommitted_changes_and_detached_head(
    qapp: QApplication, tmp_path: Path, main_repo: Path
) -> None:
    (main_repo / "README").write_text("edited\n")
    _git("-C", str(main_repo), "checkout", "-q", "--detach")
    dlg = WorktreeDialog(str(main_repo))
    dlg.findChild(QLineEdit).setText("x")
    texts = " ".join(l.text() for l in dlg.findChildren(QLabel) if not l.isHidden())
    assert "from detached HEAD at" in texts
    assert f"Uncommitted changes stay in {main_repo}" in texts


def test_ok_adds_a_selected_worktree_row_with_the_badge(
    qapp: QApplication, tmp_path: Path, main_repo: Path, monkeypatch
) -> None:
    sidebar = _sidebar(tmp_path, [str(main_repo)])
    source = sidebar.model.repo_at(0)
    sidebar.model.set_emoji(source.id, "🌱")
    sidebar.model.set_title(source.id, "Main task")
    added = []
    sidebar.repo_added.connect(added.append)
    monkeypatch.setattr(WorktreeDialog, "exec", lambda self: (self.findChild(QLineEdit).setText("fix/a"), 1)[1])

    sidebar._make_worktree(source)

    assert len(sidebar.model._store.repos) == 2
    new = sidebar.model.repo_at(1)
    assert new.path == str(main_repo.parent / "proj-fix-a")
    assert new.emoji == "🌱" and new.title == ""
    assert sidebar.model.index(1).data(ROLE_WORKTREE_OF) == "proj"
    assert sidebar._view.currentIndex().row() == 1
    assert added == [new]


def test_git_failure_shows_the_message_and_adds_no_row(
    qapp: QApplication, tmp_path: Path, main_repo: Path, monkeypatch
) -> None:
    sidebar = _sidebar(tmp_path, [str(main_repo)])

    def accept_after_a_shell_made_the_branch(self):
        self.findChild(QLineEdit).setText("late")
        _git("-C", str(main_repo), "branch", "late")
        return 1

    monkeypatch.setattr(WorktreeDialog, "exec", accept_after_a_shell_made_the_branch)
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))

    sidebar._make_worktree(sidebar.model.repo_at(0))

    assert len(sidebar.model._store.repos) == 1
    assert shown and "already exists" in shown[0]


def test_unborn_head_shows_the_message(qapp: QApplication, tmp_path: Path, monkeypatch) -> None:
    empty = Path(os.path.realpath(tmp_path)) / "empty"
    _git("init", "-q", "-b", "main", str(empty))
    sidebar = _sidebar(tmp_path, [str(empty)])
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    sidebar._make_worktree(sidebar.model.repo_at(0))
    assert shown and len(sidebar.model._store.repos) == 1


def test_failure_after_worktree_add_still_adds_the_row(
    qapp: QApplication, tmp_path: Path, main_repo: Path, monkeypatch
) -> None:
    from src.core import worktree
    sidebar = _sidebar(tmp_path, [str(main_repo)])
    monkeypatch.setattr(WorktreeDialog, "exec", lambda self: (self.findChild(QLineEdit).setText("x"), 1)[1])
    real_git = worktree._git

    def config_fails(path, *args):
        if args[0] == "config":
            raise GitError("error: could not lock config file")
        return real_git(path, *args)

    monkeypatch.setattr(worktree, "_git", config_fails)
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    sidebar._make_worktree(sidebar.model.repo_at(0))
    assert shown == ["error: could not lock config file"]
    assert sidebar.model.repo_at(1).path == str(main_repo.parent / "proj-x")
