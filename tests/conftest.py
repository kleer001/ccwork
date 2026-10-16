"""Shared pytest fixtures for the ccwork test suite.

Consolidates the `qapp` session-scoped QApplication factory and the
`stub_hook_server` factory that several MainWindow-construction tests
previously inlined verbatim.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


class StubHookServer(QObject):
    """Minimal HookServer stand-in for tests — exposes the `event_received`
    signal that `MainWindow` connects to but never fires anything itself.
    Tests that want to exercise hook-driven state usually call
    `RepoListModel.apply_hook_event` directly rather than going through
    this signal; this stub only exists so MainWindow's constructor finds
    a Qt-signal-bearing object on the `hook_server=` parameter."""

    event_received = Signal(dict)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """One QApplication for the whole session — Qt forbids more than one."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def stub_hook_server() -> StubHookServer:
    """Fresh `StubHookServer` per test — no state to share."""
    return StubHookServer()


@pytest.fixture(autouse=True)
def _isolated_runtime_dir(tmp_path_factory, monkeypatch) -> None:
    """Point XDG_RUNTIME_DIR at a temp dir for every test, so the row-title
    files ccwork publishes for the hook sink never land in the real one."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("runtime")))
