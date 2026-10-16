"""Hook events route to the row whose terminal sent them.

Each event carries the row id from `CCWORK_ROW_ID`. MainWindow applies the
event to that row only, drops events with a missing or unknown row, and
rebinds a row when its session starts in another git repo.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

from src.core.hook_server import (
    EVENT_REPO_ADDED,
    EVENT_SESSION_START,
    EVENT_STOP,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore
from src.core.settings import Settings
from src.ui.main_window import MainWindow
from src.ui.repo_sidebar import ROLE_SESSION_ACTIVE, ROLE_STATUS, STATUS_DONE

from tests.conftest import StubHookServer


def _git_init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    return path


def _event(event: str, row: str | None, cwd: str, session_id: str | None = None) -> dict:
    obj: dict = {"event": event, "cwd": cwd, "payload": {}}
    if row is not None:
        obj["row"] = row
    if session_id is not None:
        obj["payload"] = {"session_id": session_id}
    return obj


def _make_window(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, paths: list[str]
) -> tuple[MainWindow, RepoStore]:
    """MainWindow over a store saved to disk: the sidebar reloads from disk."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path=p) for p in paths]
    store.save()
    win = MainWindow(store=store, hook_server=StubHookServer(), settings=Settings())
    return win, store


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    return _git_init(tmp_path / "repo")


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo_dir: Path):
    win, _store = _make_window(qapp, tmp_path, monkeypatch, [str(repo_dir)])
    yield win
    win.close()


def _emit(win: MainWindow, obj: dict) -> None:
    win._hook_server.event_received.emit(obj)


def test_event_changes_only_its_own_row(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo_dir: Path
) -> None:
    win, store = _make_window(qapp, tmp_path, monkeypatch, [str(repo_dir), str(repo_dir)])
    try:
        first, second = (r.id for r in store.repos)
        _emit(win, _event(EVENT_USER_PROMPT_SUBMIT, first, str(repo_dir)))

        assert win._sidebar.model.is_working(first) is True
        assert win._sidebar.model.is_working(second) is False
        assert win.windowTitle() == "ccwork — 1 working"

        _emit(win, _event(EVENT_STOP, first, str(repo_dir)))
        _emit(win, _event(EVENT_USER_PROMPT_SUBMIT, second, str(repo_dir)))
        assert win._sidebar.model.is_working(first) is False
        assert win._sidebar.model.is_working(second) is True
    finally:
        win.close()


def test_status_lands_on_the_sending_duplicate_only(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo_dir: Path
) -> None:
    win, store = _make_window(qapp, tmp_path, monkeypatch, [str(repo_dir), str(repo_dir)])
    try:
        first, second = (r.id for r in store.repos)
        _emit(win, _event(EVENT_STOP, second, str(repo_dir)))
        assert win._sidebar.model.index(0).data(ROLE_STATUS) == ""
        assert win._sidebar.model.index(1).data(ROLE_STATUS) == STATUS_DONE
        assert win._sidebar.model.index(0).data(ROLE_SESSION_ACTIVE) is False
    finally:
        win.close()


@pytest.mark.parametrize("row", [None, ""])
def test_missing_row_is_dropped_with_warning(
    window: MainWindow, repo_dir: Path, caplog: pytest.LogCaptureFixture, row
) -> None:
    with caplog.at_level(logging.WARNING, logger="src.ui.main_window"):
        _emit(window, _event(EVENT_USER_PROMPT_SUBMIT, row, str(repo_dir)))

    assert window._sidebar.model.any_working() is False
    assert any(
        r.levelno == logging.WARNING and "UserPromptSubmit" in r.getMessage()
        for r in caplog.records
    )


def test_unknown_row_is_dropped_with_warning(
    window: MainWindow, repo_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="src.ui.main_window"):
        _emit(window, _event(EVENT_USER_PROMPT_SUBMIT, "no-such-row", str(repo_dir)))

    assert window._sidebar.model.any_working() is False
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_repo_added_with_row_adds_nothing(window: MainWindow, repo_dir: Path, tmp_path: Path) -> None:
    other = _git_init(tmp_path / "other")
    row_id = window._store.repos[0].id
    before = len(window._store.repos)

    _emit(window, _event(EVENT_REPO_ADDED, row_id, str(other)))

    assert len(window._store.repos) == before


def test_repo_added_without_row_adds_a_row(window: MainWindow, tmp_path: Path) -> None:
    other = _git_init(tmp_path / "other")

    _emit(window, _event(EVENT_REPO_ADDED, None, str(other)))

    assert [r.path for r in window._store.repos][-1] == os.path.realpath(other)


def test_session_start_in_subdir_does_not_rebind(
    window: MainWindow, repo_dir: Path
) -> None:
    sub = repo_dir / "sub"
    sub.mkdir()
    row = window._store.repos[0]

    _emit(window, _event(EVENT_SESSION_START, row.id, str(sub), "s1"))

    assert row.path == os.path.realpath(repo_dir)
    assert window._sidebar.model.is_session_active(row.id) is True


def test_session_start_outside_git_does_not_rebind(
    window: MainWindow, tmp_path: Path
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    row = window._store.repos[0]
    original = row.path

    _emit(window, _event(EVENT_SESSION_START, row.id, str(plain), "s1"))

    assert row.path == original


def test_session_start_in_another_repo_rebinds_the_row(
    window: MainWindow, repo_dir: Path, tmp_path: Path
) -> None:
    other = _git_init(tmp_path / "other")
    row = window._store.repos[0]
    row_id = row.id

    _emit(window, _event(EVENT_SESSION_START, row_id, str(other), "s1"))

    assert len(window._store.repos) == 1
    assert row.id == row_id
    assert row.path == os.path.realpath(other)
    assert window._sidebar.model.is_session_active(row_id) is True


def test_terminal_finish_clears_only_its_own_row(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo_dir: Path
) -> None:
    win, store = _make_window(qapp, tmp_path, monkeypatch, [str(repo_dir), str(repo_dir)])
    try:
        first, second = store.repos
        for repo in (first, second):
            _emit(win, _event(EVENT_SESSION_START, repo.id, str(repo_dir), f"s-{repo.id}"))
            _emit(win, _event(EVENT_USER_PROMPT_SUBMIT, repo.id, str(repo_dir)))
        model = win._sidebar.model

        win._on_terminal_finished(first, 0)

        assert model.is_working(first.id) is False
        assert model.is_session_active(first.id) is False
        assert model.is_working(second.id) is True
        assert model.is_session_active(second.id) is True
    finally:
        win.close()


def test_bell_follows_new_badges_only(window: MainWindow, repo_dir: Path) -> None:
    rid = window._store.repos[0].id
    ignored = _event("Notification", rid, str(repo_dir))
    ignored["payload"] = {"notification_type": "idle_prompt"}
    _emit(window, ignored)
    assert window._bell_btn._unseen is False

    asking = _event("PermissionRequest", rid, str(repo_dir))
    asking["payload"] = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    _emit(window, asking)
    assert window._bell_btn._unseen is True
