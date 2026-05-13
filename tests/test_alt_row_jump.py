"""Tests for the row-jump slot (`MainWindow._jump_to_row`).

The binding side — `Ctrl+Shift+1`..`Ctrl+Shift+9` grabbing the keys via
the MainWindow-scoped XGrabKey — is platform-dependent (needs a real
xcb display) and verified by the live scripts under `tests/live/`.
Here we exercise the dispatch slot directly: in-range hands the right
repo id to `select_id`, out-of-range emits the status-bar message, and
empty sidebar doesn't crash.

We spy on `RepoSidebar.select_id` rather than asserting on
`QListView.currentIndex()` after the fact: a successful selection
triggers `_on_repo_selected` → `_ensure_terminal` → `xterm` spawn,
which hangs under `QT_QPA_PLATFORM=offscreen`. The spy is the cheapest
seam.

The filename preserves the spec's original `alt-n-row-jump` traceability
even though the binding namespace moved to Ctrl+Shift+N during the
2026-05-13 keybinding rework.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

from src.core.repo_store import Repo, RepoStore
from src.core.settings import Settings

from tests.conftest import StubHookServer


@pytest.fixture
def main_window_with_3_repos(qapp: QApplication, tmp_path: Path,
                              monkeypatch: pytest.MonkeyPatch):
    """MainWindow with three pre-saved repos in the store.

    The save+load round-trip is necessary because `RepoSidebar` calls
    `model.reload()` → `store.load()` in its __init__, which would
    overwrite an in-memory-only `store.repos = [...]` with an empty
    list when the config file doesn't exist on disk.

    The `select_id` spy installed below intercepts the call before it
    can trigger `setCurrentIndex` → `_on_repo_selected` → xterm spawn,
    which hangs in offscreen Qt.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [
        Repo(path="/a", id="r-a"),
        Repo(path="/b", id="r-b"),
        Repo(path="/c", id="r-c"),
    ]
    store.save()
    from src.ui.main_window import MainWindow
    win = MainWindow(store=store, hook_server=StubHookServer(), settings=Settings())

    # Replace select_id with a recorder so the test can verify what _jump_to_row
    # dispatched without triggering the terminal-spawn cascade.
    calls: list[str] = []
    win._sidebar.select_id = calls.append  # type: ignore[method-assign]
    win._select_calls = calls  # type: ignore[attr-defined]

    yield win
    win.close()


def test_jump_in_range_selects_the_right_repo(main_window_with_3_repos) -> None:
    win = main_window_with_3_repos
    win._jump_to_row(1)  # zero-indexed; row 1 == repo at /b
    assert win._select_calls == ["r-b"]


def test_jump_to_first_row(main_window_with_3_repos) -> None:
    win = main_window_with_3_repos
    win._jump_to_row(0)
    assert win._select_calls == ["r-a"]


def test_jump_to_last_visible_row(main_window_with_3_repos) -> None:
    win = main_window_with_3_repos
    win._jump_to_row(2)
    assert win._select_calls == ["r-c"]


def test_jump_out_of_range_shows_status_message(main_window_with_3_repos) -> None:
    """Press Ctrl+Shift+9 with only 3 rows — message reads `No repo at slot 9`
    (1-indexed, matching the digit the user pressed) for ~1.5 s and no
    select_id call occurs."""
    win = main_window_with_3_repos
    win._jump_to_row(8)  # zero-indexed for the 9th slot
    assert win.statusBar().currentMessage() == "No repo at slot 9"
    assert win._select_calls == []


def test_jump_negative_index_also_handled(main_window_with_3_repos) -> None:
    """Defensive case — `_jump_to_row` is only called with row=n-1 for
    n in 1..9, so row<0 isn't reachable from the binding table. But the
    slot is public-shaped, so it shouldn't crash if called negatively."""
    win = main_window_with_3_repos
    win._jump_to_row(-1)
    assert win.statusBar().currentMessage() == "No repo at slot 0"
    assert win._select_calls == []


def test_jump_on_empty_sidebar_no_crash(qapp: QApplication, tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = []
    store.save()
    from src.ui.main_window import MainWindow
    win = MainWindow(store=store, hook_server=StubHookServer(), settings=Settings())
    calls: list[str] = []
    win._sidebar.select_id = calls.append  # type: ignore[method-assign]
    try:
        win._jump_to_row(0)
        assert win.statusBar().currentMessage() == "No repo at slot 1"
        assert calls == []
    finally:
        win.close()


def test_status_message_uses_one_indexed_slot_number(main_window_with_3_repos) -> None:
    """The `row+1` translation in the slot must produce slot numbers that
    match the user-visible digit. Lock down the off-by-one direction."""
    win = main_window_with_3_repos
    win._jump_to_row(5)
    assert "slot 6" in win.statusBar().currentMessage()
    win._jump_to_row(3)
    assert "slot 4" in win.statusBar().currentMessage()
