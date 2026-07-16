"""Tests for the Dashboard overlay navigation.

The sidebar's Dashboard button swaps the terminal stack to the splash
(`_empty_placeholder`) as an *overlay*: the sidebar selection and the
current repo's terminal are untouched. Two return paths: re-clicking the
already-current row (via the view's ``clicked`` signal — ``repo_selected``
only fires on selection *change*) and Esc on the splash (event filter in
MainWindow).

A `FakeHost` stands in for TerminalHost — a real xterm spawn hangs under
`QT_QPA_PLATFORM=offscreen`. It is pre-registered in `win._terminals`
before the row is selected, so `_ensure_terminal` returns it instead of
spawning.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from src.core.repo_store import Repo, RepoStore
from src.core.settings import Settings

from tests.conftest import StubHookServer


class FakeHost(QWidget):
    """Minimal TerminalHost stand-in: the API surface MainWindow touches."""

    def focus_child(self) -> None:
        pass

    def is_running(self) -> bool:
        return True

    def apply_live_settings(self, xterm_settings) -> list[str]:
        return []

    def stop(self) -> None:
        pass


def _make_store(tmp_path: Path, repos: list[Repo]) -> RepoStore:
    # Save + reload round-trip: RepoSidebar.__init__ calls model.reload()
    # → store.load(), which would wipe in-memory-only repos.
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = repos
    store.save()
    return store


@pytest.fixture
def win(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """MainWindow with one repo selected and a fake live terminal current."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = _make_store(tmp_path, [Repo(path="/a", id="r-a")])
    from src.ui.main_window import MainWindow
    w = MainWindow(store=store, hook_server=StubHookServer(), settings=Settings())
    host = FakeHost()
    w._terminals["r-a"] = host
    w._stack.addWidget(host)
    w._sidebar.select_id("r-a")  # → _on_repo_selected → setCurrentWidget(host)
    assert w._stack.currentWidget() is host
    w._host = host  # type: ignore[attr-defined]
    yield w
    w.close()


def test_dashboard_button_emits_signal(qapp: QApplication, tmp_path: Path) -> None:
    from src.ui.repo_sidebar import RepoSidebar
    store = _make_store(tmp_path, [Repo(path="/a", id="r-a")])
    sidebar = RepoSidebar(store)
    fired: list[None] = []
    sidebar.dashboard_requested.connect(lambda: fired.append(None))
    sidebar._dashboard_btn.click()
    assert len(fired) == 1


def test_dashboard_sits_beside_recent_at_stack_tail(
    qapp: QApplication, tmp_path: Path
) -> None:
    """Both tail slots are viewport-parented row-clones glued side by side
    just under the last row: Recent left, Dashboard right, same baseline."""
    from src.ui.repo_sidebar import RepoSidebar
    store = _make_store(tmp_path, [Repo(path="/a", id="r-a"), Repo(path="/b", id="r-b")])
    sidebar = RepoSidebar(store)
    sidebar.resize(220, 400)
    sidebar.show()
    vp = sidebar._view.viewport()
    assert sidebar._dashboard_btn.parent() is vp
    assert sidebar._recent_btn.parent() is vp
    last = sidebar._view.visualRect(sidebar.model.index(1))
    assert sidebar._recent_btn.y() == last.bottom() + 1
    assert sidebar._dashboard_btn.y() == sidebar._recent_btn.y()
    assert sidebar._dashboard_btn.x() > sidebar._recent_btn.x() + sidebar._recent_btn.width() - 1
    assert not sidebar._dashboard_btn.isHidden()


def test_dashboard_swaps_to_placeholder_without_deselecting(win) -> None:
    win._sidebar._dashboard_btn.click()
    assert win._stack.currentWidget() is win._empty_placeholder
    # Selection untouched...
    assert win._sidebar.current_repo().id == "r-a"
    # ...and the terminal is still alive underneath.
    assert win._terminals["r-a"] is win._host


def test_reclick_current_row_returns_to_terminal(win) -> None:
    win._sidebar._dashboard_btn.click()
    assert win._stack.currentWidget() is win._empty_placeholder
    # A click on the already-current row emits the view's clicked signal
    # but no currentChanged — exactly the case repo_clicked exists for.
    idx = win._sidebar.model.index(0)
    win._sidebar._view.clicked.emit(idx)
    assert win._stack.currentWidget() is win._host


def test_click_is_noop_when_terminal_already_showing(win) -> None:
    idx = win._sidebar.model.index(0)
    win._sidebar._view.clicked.emit(idx)
    assert win._stack.currentWidget() is win._host


def test_escape_returns_to_terminal(win) -> None:
    win._sidebar._dashboard_btn.click()
    assert win._stack.currentWidget() is win._empty_placeholder
    QTest.keyClick(win._empty_placeholder, Qt.Key_Escape)
    assert win._stack.currentWidget() is win._host


def test_escape_noop_without_terminal(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No selection, no terminal: the button still shows the splash (a
    no-op — it's already current) and Esc does nothing."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = _make_store(tmp_path, [])
    from src.ui.main_window import MainWindow
    w = MainWindow(store=store, hook_server=StubHookServer(), settings=Settings())
    try:
        w._sidebar._dashboard_btn.click()
        assert w._stack.currentWidget() is w._empty_placeholder
        QTest.keyClick(w._empty_placeholder, Qt.Key_Escape)
        assert w._stack.currentWidget() is w._empty_placeholder
    finally:
        w.close()
