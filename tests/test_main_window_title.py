"""Tests for the working-count suffix in the main window title.

The title is driven by `RepoListModel.working_changed`, which fires on
the True↔False edge inside `set_working`. The suffix counts working rows,
so duplicate rows on the same path each count.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

from src.core.hook_server import (
    EVENT_NOTIFICATION,
    EVENT_STOP,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore
from src.core.settings import Settings

from tests.conftest import StubHookServer
from src.ui.main_window import MainWindow


@pytest.fixture
def store(tmp_path: Path) -> RepoStore:
    s = RepoStore(config_path=tmp_path / "repos.json")
    s.repos = [
        Repo(path="/a"),
        Repo(path="/b"),
    ]
    return s


def _row_id(win: MainWindow, path: str) -> str:
    return next(r.id for r in win._store.repos if r.path == path)


@pytest.fixture
def main_window(qapp: QApplication, store: RepoStore, tmp_path: Path,
                monkeypatch: pytest.MonkeyPatch):
    # Sandbox settings.toml so saves don't touch the user's real config.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # The sidebar reloads the store from disk, so the rows must be saved first.
    store.save()
    win = MainWindow(store=store, hook_server=StubHookServer(), settings=Settings())
    yield win
    win.close()


def test_title_no_suffix_when_idle(main_window) -> None:
    assert main_window.windowTitle() == "ccwork"


def test_title_increments_on_user_prompt_submit(main_window) -> None:
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, _row_id(main_window, "/a"))
    assert main_window.windowTitle() == "ccwork — 1 working"


def test_title_counts_two_distinct_repos(main_window) -> None:
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, _row_id(main_window, "/a"))
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, _row_id(main_window, "/b"))
    assert main_window.windowTitle() == "ccwork — 2 working"


def test_title_decrements_on_stop(main_window) -> None:
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, _row_id(main_window, "/a"))
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, _row_id(main_window, "/b"))
    main_window._sidebar.apply_hook_event(EVENT_STOP, _row_id(main_window, "/a"))
    assert main_window.windowTitle() == "ccwork — 1 working"


def test_title_returns_to_idle_when_all_stop(main_window) -> None:
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, _row_id(main_window, "/a"))
    main_window._sidebar.apply_hook_event(EVENT_STOP, _row_id(main_window, "/a"))
    assert main_window.windowTitle() == "ccwork"


def test_title_unchanged_by_notification(main_window) -> None:
    """Notification fires mid-turn (permission_prompt) and does not touch
    the working flag — title must not bump."""
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, _row_id(main_window, "/a"))
    before = main_window.windowTitle()
    main_window._sidebar.apply_hook_event(
        EVENT_NOTIFICATION, _row_id(main_window, "/a"), {"notification_type": "permission_prompt"},
    )
    assert main_window.windowTitle() == before  # still "ccwork — 1 working"


def test_title_counts_duplicate_rows_separately(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two sidebar rows pointing at the same path are two working rows.
    Each row runs its own Claude session, so each counts."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path="/shared", id="r1"), Repo(path="/shared", id="r2")]
    store.save()
    win = MainWindow(store=store, hook_server=StubHookServer(), settings=Settings())
    try:
        win._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "r1")
        assert win.windowTitle() == "ccwork — 1 working"
        win._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "r2")
        assert win.windowTitle() == "ccwork — 2 working"
        # A second UPS on the same row is a no-op for the working set.
        win._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "r1")
        assert win.windowTitle() == "ccwork — 2 working"
    finally:
        win.close()


def test_working_changed_fires_once_per_edge(qapp: QApplication, tmp_path: Path) -> None:
    """Calling set_working repeatedly with the same value emits the signal
    only on the actual True↔False transition. Guards against title-update
    storms from broadcast row repaints."""
    from src.ui.repo_sidebar import RepoListModel
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path="/a")]
    model = RepoListModel(store)

    fired = []
    model.working_changed.connect(lambda: fired.append(None))

    rid = store.repos[0].id
    model.set_working(rid, True)       # edge: emit
    model.set_working(rid, True)       # no-op: no emit
    model.set_working(rid, True)       # no-op: no emit
    model.set_working(rid, False)      # edge: emit
    model.set_working(rid, False)      # no-op: no emit

    assert len(fired) == 2
