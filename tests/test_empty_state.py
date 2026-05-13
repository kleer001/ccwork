"""Tests for the empty-state placeholder shown when no terminal is current.

The widget is static (no signals, no per-state variants). What we lock
down here is: the heading text, the version-and-tagline subhead, the
exact set of hints shipped (so adding one is a deliberate spec edit,
not a stealthy regression), and the silent-hide behavior when the logo
SVG isn't where we expect it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from src.core.repo_store import RepoStore
from src.core.settings import Settings
from src.ui.empty_state import EmptyState, HINT_LINES


class _StubHookServer(QObject):
    event_received = Signal(dict)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_heading_text_is_ccwork(qapp: QApplication) -> None:
    es = EmptyState(version="9.9.9")
    assert es._heading.text() == "ccwork"


def test_subhead_includes_version_string(qapp: QApplication) -> None:
    es = EmptyState(version="9.9.9")
    assert "9.9.9" in es._subhead.text()
    assert "Claude Code" in es._subhead.text()


def test_renders_without_logo(qapp: QApplication, tmp_path: Path) -> None:
    """Missing logo file → image label hidden, heading/hints still render."""
    es = EmptyState(version="0.1.0", logo_path=tmp_path / "does-not-exist.svg")
    assert es._logo.isHidden()
    assert es._heading.text() == "ccwork"
    assert len(es._hints) == len(HINT_LINES)


def test_hint_count_matches_shipped_set(qapp: QApplication) -> None:
    """Four hints shipped: Ctrl+Shift+O / right-click / Ctrl+Shift+P / F1.
    The F1 entry was added with the keyboard-cheatsheet spec (Wave 3).
    Future additions must be deliberate edits to HINT_LINES, not side
    effects."""
    es = EmptyState(version="0.1.0")
    assert len(es._hints) == 4
    assert len(HINT_LINES) == 4


def test_hints_reference_current_shortcut_namespace(qapp: QApplication) -> None:
    """Hints must use the Ctrl+Shift+N namespace shipped 2026-05-13 and
    advertise the F1 cheatsheet trigger added in Wave 3. Guards against a
    future doc-rot where the empty-state shows a shortcut that doesn't
    exist."""
    es = EmptyState(version="0.1.0")
    joined = " ".join(h.text() for h in es._hints)
    assert "Ctrl+Shift+O" in joined  # add a repo
    assert "Ctrl+Shift+P" in joined  # preferences
    assert "F1" in joined            # cheatsheet
    # Old shortcuts that were dropped must NOT appear.
    assert "Ctrl+O" not in joined.replace("Ctrl+Shift+O", "")
    assert "Ctrl+," not in joined


def test_shown_at_startup_when_no_repos(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh MainWindow with an empty repo store should display the
    EmptyState in its central stack."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = []
    store.save()
    from src.ui.main_window import MainWindow
    win = MainWindow(store=store, hook_server=_StubHookServer(), settings=Settings())
    try:
        assert win._stack.currentWidget() is win._empty_placeholder
        assert isinstance(win._empty_placeholder, EmptyState)
    finally:
        win.close()
