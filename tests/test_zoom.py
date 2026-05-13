"""Tests for the Ctrl+zoom plumbing in MainWindow.

Covers the numeric behavior of `_on_zoom_requested` — clamp bounds, delta
application, and reset-from-disk. The X11 grab code and Qt event routing in
TerminalHost need a real X server, so they're excluded.
"""

from __future__ import annotations

import pytest

from PySide6.QtWidgets import QApplication

from src.core.repo_store import RepoStore
from src.core.settings import Settings, XtermSettings, save_settings

from tests.conftest import StubHookServer


@pytest.fixture
def main_window(qapp: QApplication, tmp_path, monkeypatch: pytest.MonkeyPatch):
    # Redirect the settings path so load_settings() in _on_zoom_requested
    # doesn't touch the user's real config.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # RepoStore also reads from XDG — fine, tmp_path is empty so it loads
    # no repos.
    store = RepoStore()
    store.load()
    from src.ui.main_window import MainWindow  # import after env override
    win = MainWindow(store=store, hook_server=StubHookServer(), settings=Settings(xterm=XtermSettings(font_size=10)))
    yield win
    win.close()


class _RecordingHost:
    """Stand-in for TerminalHost that records apply_live_settings calls."""
    def __init__(self) -> None:
        self.applied: list[int] = []

    def apply_live_settings(self, xt: XtermSettings) -> list[str]:
        self.applied.append(int(xt.font_size))
        return []

    def stop(self) -> None:
        # Called by MainWindow.closeEvent during test teardown.
        pass

    def is_running(self) -> bool:
        # Test stand-in: never "running" so closeEvent doesn't prompt.
        return False


def test_zoom_in_increments_font_size(main_window) -> None:
    host = _RecordingHost()
    main_window._terminals["/fake"] = host  # type: ignore[assignment]
    main_window._on_zoom_requested(+1)
    assert main_window._settings.xterm.font_size == 11
    assert host.applied == [11]


def test_zoom_out_decrements_font_size(main_window) -> None:
    host = _RecordingHost()
    main_window._terminals["/fake"] = host  # type: ignore[assignment]
    main_window._on_zoom_requested(-1)
    assert main_window._settings.xterm.font_size == 9
    assert host.applied == [9]


def test_zoom_clamps_at_upper_bound(main_window) -> None:
    main_window._settings.xterm.font_size = 48
    host = _RecordingHost()
    main_window._terminals["/fake"] = host  # type: ignore[assignment]
    main_window._on_zoom_requested(+1)
    assert main_window._settings.xterm.font_size == 48
    # At the clamp, we skip the apply call entirely (no-op).
    assert host.applied == []


def test_zoom_clamps_at_lower_bound(main_window) -> None:
    main_window._settings.xterm.font_size = 6
    host = _RecordingHost()
    main_window._terminals["/fake"] = host  # type: ignore[assignment]
    main_window._on_zoom_requested(-1)
    assert main_window._settings.xterm.font_size == 6
    assert host.applied == []


def test_zoom_reset_reloads_from_disk(main_window, tmp_path) -> None:
    # Persist a known size, then nudge in-memory to something else, then
    # reset and confirm we're back to the persisted value.
    save_settings(Settings(xterm=XtermSettings(font_size=13)))
    main_window._settings.xterm.font_size = 99
    host = _RecordingHost()
    main_window._terminals["/fake"] = host  # type: ignore[assignment]
    main_window._on_zoom_requested(0)
    assert main_window._settings.xterm.font_size == 13
    assert host.applied == [13]


def test_zoom_applies_to_every_terminal(main_window) -> None:
    h1, h2, h3 = _RecordingHost(), _RecordingHost(), _RecordingHost()
    main_window._terminals["/a"] = h1  # type: ignore[assignment]
    main_window._terminals["/b"] = h2  # type: ignore[assignment]
    main_window._terminals["/c"] = h3  # type: ignore[assignment]
    main_window._on_zoom_requested(+1)
    assert h1.applied == h2.applied == h3.applied == [11]
