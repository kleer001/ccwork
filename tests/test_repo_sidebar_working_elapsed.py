"""Tests for the per-turn elapsed-time tooltip extension.

The model stamps a turn-start monotonic timestamp on UserPromptSubmit,
clears it on Stop, and appends a `Working {elapsed}` line to the
`Qt.ToolTipRole` payload for working rows that have a recorded start.
We monkeypatch `time.monotonic` in `src.ui.repo_sidebar` to control the
stamp/read clock deterministically.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.core.hook_server import (
    EVENT_NOTIFICATION,
    EVENT_STOP,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore
from src.ui import repo_sidebar
from src.ui.repo_sidebar import RepoListModel, _format_elapsed


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _store_with(repo_path: str, cfg_path: Path) -> RepoStore:
    store = RepoStore(config_path=cfg_path)
    store.repos = [Repo(path=repo_path)]
    return store


class _Clock:
    """Hand-cranked monotonic source. Replaces time.monotonic in the module
    under test so stamp/read pairs are deterministic."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    c = _Clock()
    monkeypatch.setattr(repo_sidebar.time, "monotonic", c)
    return c


def test_ups_stamps_turn_start(qapp: QApplication, tmp_path: Path, clock: _Clock) -> None:
    store = _store_with("/a", tmp_path / "repos.json")
    model = RepoListModel(store)

    clock.t = 1234.5
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/a")

    assert model._turn_started["/a"] == 1234.5


def test_tooltip_elapsed_format_bands(
    qapp: QApplication, tmp_path: Path, clock: _Clock
) -> None:
    store = _store_with("/a", tmp_path / "repos.json")
    model = RepoListModel(store)

    clock.t = 0.0
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/a")
    idx = model.index(0)

    # Seconds band.
    clock.t = 27.0
    assert idx.data(Qt.ToolTipRole).endswith("\nWorking 27s")

    # Minutes band.
    clock.t = 83.0
    assert idx.data(Qt.ToolTipRole).endswith("\nWorking 1m 23s")

    # Hours band.
    clock.t = 3725.0
    assert idx.data(Qt.ToolTipRole).endswith("\nWorking 1h 2m")


def test_stop_clears_turn_start_and_tooltip(
    qapp: QApplication, tmp_path: Path, clock: _Clock
) -> None:
    store = _store_with("/a", tmp_path / "repos.json")
    model = RepoListModel(store)

    clock.t = 100.0
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/a")
    clock.t = 130.0
    model.apply_hook_event(EVENT_STOP, "/a")

    assert "/a" not in model._turn_started
    tooltip = model.index(0).data(Qt.ToolTipRole)
    assert "Working " not in tooltip  # no "Working Ns" line in DONE state
    assert tooltip.startswith("Claude finished a turn\n/a")


def test_interrupted_turn_resets_timer(
    qapp: QApplication, tmp_path: Path, clock: _Clock
) -> None:
    store = _store_with("/a", tmp_path / "repos.json")
    model = RepoListModel(store)

    clock.t = 50.0
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/a")
    assert model._turn_started["/a"] == 50.0

    # Second UPS without an intervening Stop — interrupted turn restarts
    # the elapsed clock from zero.
    clock.t = 80.0
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/a")
    assert model._turn_started["/a"] == 80.0


def test_working_true_without_ups_falls_back_to_two_line_tooltip(
    qapp: QApplication, tmp_path: Path, clock: _Clock
) -> None:
    """Bypassing apply_hook_event (or surviving a ccwork restart mid-turn)
    leaves _working True but _turn_started empty. Tooltip must not raise."""
    store = _store_with("/a", tmp_path / "repos.json")
    model = RepoListModel(store)

    model.set_working("/a", True)
    tooltip = model.index(0).data(Qt.ToolTipRole)

    assert tooltip == "Claude is working…\n/a"


def test_notification_does_not_touch_turn_start(
    qapp: QApplication, tmp_path: Path, clock: _Clock
) -> None:
    """Notification fires mid-turn (permission_prompt) — the elapsed clock
    must keep running, not reset and not stop."""
    store = _store_with("/a", tmp_path / "repos.json")
    model = RepoListModel(store)

    clock.t = 10.0
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/a")
    clock.t = 25.0
    model.apply_hook_event(EVENT_NOTIFICATION, "/a")

    assert model._turn_started["/a"] == 10.0  # unchanged


def test_format_elapsed_unit_table() -> None:
    assert _format_elapsed(0) == "0s"
    assert _format_elapsed(59) == "59s"
    assert _format_elapsed(60) == "1m 0s"
    assert _format_elapsed(3599) == "59m 59s"
    assert _format_elapsed(3600) == "1h 0m"
    # A few interesting interior points.
    assert _format_elapsed(83) == "1m 23s"
    assert _format_elapsed(3725) == "1h 2m"
