"""A new terminal takes the keyboard focus when its xterm window maps: the
host sees the MapNotify on Qt's X connection and emits `mapped`, and
MainWindow focuses that xterm only while it is the current terminal and
ccwork is the active window. The X side runs in `tests/live/`."""

from __future__ import annotations

import ctypes
from pathlib import Path

import pytest

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from src.core import x11
from src.core.repo_store import RepoStore
from src.core.settings import Settings
from src.ui.terminal_host import TerminalHost, _MapNotifyFilter, _XcbMapNotifyEvent

from tests.conftest import StubHookServer

XCB_UNMAP_NOTIFY = 18


def _send(filt: _MapNotifyFilter, kind: int, window: int, event_type: bytes = x11.XCB_EVENT_TYPE) -> tuple:
    ev = _XcbMapNotifyEvent(response_type=kind, window=window)
    return filt.nativeEventFilter(event_type, ctypes.addressof(ev))


def test_the_filter_calls_back_once_on_the_map_of_its_window() -> None:
    calls = []
    filt = _MapNotifyFilter(0x400001, lambda: calls.append(1))
    assert _send(filt, x11.XCB_MAP_NOTIFY, 0x400002) == (False, 0)
    assert _send(filt, XCB_UNMAP_NOTIFY, 0x400001) == (False, 0)
    assert _send(filt, x11.XCB_MAP_NOTIFY, 0x400001, b"windows_generic_MSG") == (False, 0)
    assert calls == []
    assert _send(filt, x11.XCB_MAP_NOTIFY | 0x80, 0x400001) == (False, 0)  # a SendEvent copy counts
    _send(filt, x11.XCB_MAP_NOTIFY, 0x400001)
    assert calls == [1]


def test_the_filter_goes_when_the_xterm_exits(qapp: QApplication) -> None:
    host = TerminalHost(argv=[])
    host._map_filter = _MapNotifyFilter(0x400001, lambda: None)
    qapp.installNativeEventFilter(host._map_filter)
    host._on_finished(0, QProcess.NormalExit)
    assert host._map_filter is None


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.save()
    from src.ui.main_window import MainWindow
    win = MainWindow(store=store, hook_server=StubHookServer(), settings=Settings())
    yield win
    win.close()


def _host(win, monkeypatch: pytest.MonkeyPatch, focused: list) -> TerminalHost:
    host = TerminalHost(argv=[], parent=win._stack)
    monkeypatch.setattr(host, "focus_child", lambda: focused.append(host))
    win._stack.addWidget(host)
    return host


@pytest.mark.parametrize("current, active, takes_focus", [
    (True, True, True),
    (False, True, False),   # another row's terminal is on top
    (True, False, False),   # a dialog or another app is the active window
])
def test_a_mapped_terminal_takes_the_focus_only_when_current_and_active(
    window, monkeypatch: pytest.MonkeyPatch, current: bool, active: bool, takes_focus: bool
) -> None:
    focused: list = []
    host, other = _host(window, monkeypatch, focused), _host(window, monkeypatch, focused)
    window._stack.setCurrentWidget(host if current else other)
    monkeypatch.setattr(window, "isActiveWindow", lambda: active)
    window._focus_if_current(host)
    assert focused == ([host] if takes_focus else [])
