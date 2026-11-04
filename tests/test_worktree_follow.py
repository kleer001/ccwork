"""A row follows Claude Code into a worktree of its repository and back out.

The payloads mirror `research/claude-worktree-hook-probe/`: with `claude -w`
the sink `cwd` and the payload `cwd` are both the worktree; after
`EnterWorktree` the sink `cwd` stays the main checkout (`CLAUDE_PROJECT_DIR`)
and only the payload `cwd` is the worktree. Spec: `docs/specs/worktree.md`
section 6.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

from src.core.hook_server import (
    EVENT_CLAUDE_EXITED,
    EVENT_SESSION_START,
    EVENT_STOP,
    EVENT_SUBAGENT_START,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore
from src.core.settings import Settings
from src.ui.main_window import MainWindow
from src.ui.repo_sidebar import ROLE_PATH_MISSING

from tests.conftest import StubHookServer
from tests.test_row_routing import _git_init


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def _commit(repo: Path) -> None:
    (repo / "README").write_text("seed\n")
    _git("-C", str(repo), "add", "README")
    _git("-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")


def _event(event: str, row: str, sink_cwd: Path, payload_cwd: Path) -> dict:
    return {"event": event, "row": row, "cwd": str(sink_cwd),
            "payload": {"session_id": "s1", "cwd": str(payload_cwd)}}


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    repo = _git_init(tmp_path / "proj")
    _commit(repo)
    return Path(os.path.realpath(repo))


@pytest.fixture
def claude_wt(main_repo: Path) -> Path:
    """A worktree where Claude Code puts one: `.claude/worktrees/<name>`."""
    wt = main_repo / ".claude" / "worktrees" / "x"
    _git("-C", str(main_repo), "worktree", "add", "-q", "-b", "worktree-x", str(wt), "HEAD")
    return wt


def _window(qapp, tmp_path, monkeypatch, repos: list[Repo]) -> MainWindow:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = repos
    store.save()
    return MainWindow(store=store, hook_server=StubHookServer(), settings=Settings())


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, main_repo: Path):
    win = _window(qapp, tmp_path, monkeypatch, [Repo(path=str(main_repo))])
    yield win
    win.close()


def _emit(win: MainWindow, obj: dict) -> None:
    win._hook_server.event_received.emit(obj)


def _on_disk(win: MainWindow) -> RepoStore:
    store = RepoStore(config_path=win._store.config_path)
    store.load()
    return store


def test_claude_w_follows_in_and_returns_home_on_exit(
    window: MainWindow, main_repo: Path, claude_wt: Path
) -> None:
    row = window._store.repos[0]

    _emit(window, _event(EVENT_SESSION_START, row.id, claude_wt, claude_wt))
    assert row.path == str(claude_wt)
    assert row.home == str(main_repo)
    assert _on_disk(window).repos[0].home == str(main_repo)

    # Claude removes a clean worktree at exit, then bin/claude sends ClaudeExited.
    _git("-C", str(main_repo), "worktree", "remove", str(claude_wt))
    _emit(window, _event(EVENT_CLAUDE_EXITED, row.id, main_repo, main_repo))

    assert row.path == str(main_repo)
    assert row.home == ""
    assert window._sidebar.model.data(window._sidebar.model.index(0), ROLE_PATH_MISSING) is False
    assert window._store.recent == []
    assert _on_disk(window).recent == []


def test_enter_worktree_follows_on_the_payload_cwd(
    window: MainWindow, main_repo: Path, claude_wt: Path
) -> None:
    row = window._store.repos[0]
    _emit(window, _event(EVENT_SESSION_START, row.id, main_repo, main_repo))
    assert row.path == str(main_repo)

    # After EnterWorktree the sink cwd stays the main checkout.
    _emit(window, _event(EVENT_STOP, row.id, main_repo, claude_wt))
    assert row.path == str(claude_wt)
    assert row.home == str(main_repo)

    # After ExitWorktree the next prompt runs in the main checkout again.
    _emit(window, _event(EVENT_USER_PROMPT_SUBMIT, row.id, main_repo, main_repo))
    assert row.path == str(main_repo)
    assert row.home == ""
    assert window._store.recent == []


def test_exit_worktree_with_remove_follows_back_on_the_same_stop(
    window: MainWindow, main_repo: Path, claude_wt: Path
) -> None:
    row = window._store.repos[0]
    _emit(window, _event(EVENT_STOP, row.id, main_repo, claude_wt))
    assert row.path == str(claude_wt)

    # ExitWorktree with action remove deletes the folder before the turn's Stop.
    _git("-C", str(main_repo), "worktree", "remove", str(claude_wt))
    _emit(window, _event(EVENT_STOP, row.id, main_repo, main_repo))
    assert row.path == str(main_repo)
    assert row.home == ""
    assert window._store.recent == []


def test_follow_into_a_sibling_worktree(
    window: MainWindow, main_repo: Path
) -> None:
    sibling = main_repo.parent / "proj-fix"
    _git("-C", str(main_repo), "worktree", "add", "-q", "-b", "fix", str(sibling), "HEAD")
    row = window._store.repos[0]

    _emit(window, _event(EVENT_USER_PROMPT_SUBMIT, row.id, sibling, sibling))

    assert row.path == str(sibling)
    assert row.home == str(main_repo)


def test_a_row_whose_home_is_gone_still_follows_in_its_repository(
    window: MainWindow, main_repo: Path, claude_wt: Path
) -> None:
    sibling = main_repo.parent / "proj-fix"
    _git("-C", str(main_repo), "worktree", "add", "-q", "-b", "fix", str(sibling), "HEAD")
    row = window._store.repos[0]
    window._sidebar.rebind(row.id, str(sibling))
    _emit(window, _event(EVENT_STOP, row.id, sibling, claude_wt))
    assert row.home == str(sibling)

    _git("-C", str(main_repo), "worktree", "remove", str(sibling))
    _emit(window, _event(EVENT_STOP, row.id, sibling, main_repo))
    assert row.path == str(main_repo)


def test_home_stays_the_first_folder_across_two_worktrees(
    window: MainWindow, main_repo: Path, claude_wt: Path
) -> None:
    second = main_repo / ".claude" / "worktrees" / "y"
    _git("-C", str(main_repo), "worktree", "add", "-q", "-b", "worktree-y", str(second), "HEAD")
    row = window._store.repos[0]

    _emit(window, _event(EVENT_STOP, row.id, main_repo, claude_wt))
    _emit(window, _event(EVENT_STOP, row.id, main_repo, second))

    assert row.path == str(second)
    assert row.home == str(main_repo)


def test_subagent_event_never_moves_the_row(
    window: MainWindow, main_repo: Path, claude_wt: Path
) -> None:
    row = window._store.repos[0]

    _emit(window, _event(EVENT_SUBAGENT_START, row.id, main_repo, claude_wt))

    assert row.path == str(main_repo)
    assert row.home == ""


def test_prompt_in_another_repo_does_not_rebind(
    window: MainWindow, main_repo: Path, tmp_path: Path
) -> None:
    other = _git_init(tmp_path / "other")
    row = window._store.repos[0]

    _emit(window, _event(EVENT_USER_PROMPT_SUBMIT, row.id, other, other))

    assert row.path == str(main_repo)


def test_session_start_in_another_repo_rebinds_without_home(
    window: MainWindow, tmp_path: Path
) -> None:
    other = Path(os.path.realpath(_git_init(tmp_path / "other")))
    row = window._store.repos[0]

    _emit(window, _event(EVENT_SESSION_START, row.id, other, other))

    assert row.path == str(other)
    assert row.home == ""


def test_follow_in_adds_the_exclude_line_once(
    window: MainWindow, main_repo: Path, claude_wt: Path
) -> None:
    row = window._store.repos[0]
    assert "?? .claude/" in _git("-C", str(main_repo), "status", "--porcelain")

    _emit(window, _event(EVENT_STOP, row.id, main_repo, claude_wt))
    _emit(window, _event(EVENT_USER_PROMPT_SUBMIT, row.id, main_repo, main_repo))
    _emit(window, _event(EVENT_STOP, row.id, main_repo, claude_wt))

    exclude = (main_repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert exclude.count("/.claude/worktrees/") == 1
    assert _git("-C", str(main_repo), "status", "--porcelain") == ""


def test_startup_returns_a_row_on_a_missing_folder_home(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, main_repo: Path
) -> None:
    gone = main_repo / ".claude" / "worktrees" / "gone"
    win = _window(qapp, tmp_path, monkeypatch, [Repo(path=str(gone), home=str(main_repo))])
    try:
        row = win._store.repos[0]
        assert row.path == str(main_repo)
        assert row.home == ""
        assert _on_disk(win).repos[0].home == ""
    finally:
        win.close()


def test_startup_keeps_a_row_whose_folder_exists(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    main_repo: Path, claude_wt: Path,
) -> None:
    win = _window(qapp, tmp_path, monkeypatch, [Repo(path=str(claude_wt), home=str(main_repo))])
    try:
        row = win._store.repos[0]
        assert row.path == str(claude_wt)
        assert row.home == str(main_repo)
    finally:
        win.close()
