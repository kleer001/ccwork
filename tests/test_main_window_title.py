"""Tests for the working-count suffix in the main window title.

The title is driven by `RepoListModel.working_changed`, which fires on
the True↔False edge inside `set_working`. The suffix is path-keyed so
duplicate rows on the same path count once.
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


@pytest.fixture
def store(tmp_path: Path) -> RepoStore:
    s = RepoStore(config_path=tmp_path / "repos.json")
    s.repos = [
        Repo(path="/a"),
        Repo(path="/b"),
    ]
    return s


@pytest.fixture
def main_window(qapp: QApplication, store: RepoStore, tmp_path: Path,
                monkeypatch: pytest.MonkeyPatch):
    # Sandbox settings.toml so saves don't touch the user's real config.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from src.ui.main_window import MainWindow
    win = MainWindow(store=store, hook_server=StubHookServer(), settings=Settings())
    yield win
    win.close()


def test_title_no_suffix_when_idle(main_window) -> None:
    assert main_window.windowTitle() == "ccwork"


def test_title_increments_on_user_prompt_submit(main_window) -> None:
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/a")
    assert main_window.windowTitle() == "ccwork — 1 working"


def test_title_counts_two_distinct_repos(main_window) -> None:
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/a")
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/b")
    assert main_window.windowTitle() == "ccwork — 2 working"


def test_title_decrements_on_stop(main_window) -> None:
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/a")
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/b")
    main_window._sidebar.apply_hook_event(EVENT_STOP, "/a")
    assert main_window.windowTitle() == "ccwork — 1 working"


def test_title_returns_to_idle_when_all_stop(main_window) -> None:
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/a")
    main_window._sidebar.apply_hook_event(EVENT_STOP, "/a")
    assert main_window.windowTitle() == "ccwork"


def test_title_unchanged_by_notification(main_window) -> None:
    """Notification fires mid-turn (permission_prompt) and does not touch
    the working flag — title must not bump."""
    main_window._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/a")
    before = main_window.windowTitle()
    main_window._sidebar.apply_hook_event(EVENT_NOTIFICATION, "/a")
    assert main_window.windowTitle() == before  # still "ccwork — 1 working"


def test_title_counts_duplicate_rows_once(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two sidebar rows pointing at the same path → one working repo, not two.
    Matches `_working`'s normalized-path semantics."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path="/shared", id="r1"), Repo(path="/shared", id="r2")]
    from src.ui.main_window import MainWindow
    win = MainWindow(store=store, hook_server=StubHookServer(), settings=Settings())
    try:
        win._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/shared")
        assert win.windowTitle() == "ccwork — 1 working"
        # A second UPS on the same path is a no-op for the working set —
        # set_working(path, True) short-circuits on the already-True case.
        win._sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/shared")
        assert win.windowTitle() == "ccwork — 1 working"
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

    model.set_working("/a", True)       # edge: emit
    model.set_working("/a", True)       # no-op: no emit
    model.set_working("/a", True)       # no-op: no emit
    model.set_working("/a", False)      # edge: emit
    model.set_working("/a", False)      # no-op: no emit

    assert len(fired) == 2
