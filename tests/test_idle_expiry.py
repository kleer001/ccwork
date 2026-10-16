"""Idle rows leave the sidebar for Recent when the expiry setting is on.

`Repo.last_used` is stamped by Claude events and clicks (at most once an
hour per row); `MainWindow._expire_idle_rows` removes rows idle longer than
`ui.expire_idle_days`, except rows with a terminal.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.core.repo_store import Repo, RepoStore
from src.core.settings import Settings, UISettings
from src.ui.main_window import MainWindow
from src.ui.preferences_dialog import PreferencesDialog

from tests.conftest import StubHookServer

DAY = 86400


def _window(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ages_days: list[float], *, enabled: bool, days: int = 30,
) -> tuple[MainWindow, RepoStore]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    store = RepoStore(config_path=tmp_path / "repos.json")
    now = time.time()
    store.repos = [
        Repo(path=str(tmp_path / f"r{i}"), last_used=now - age * DAY)
        for i, age in enumerate(ages_days)
    ]
    store.save()
    settings = Settings()
    settings.ui = UISettings(expire_idle_repos=enabled, expire_idle_days=days)
    win = MainWindow(store=store, hook_server=StubHookServer(), settings=settings)
    return win, store


def test_idle_row_moves_to_recent_at_startup(qapp, tmp_path, monkeypatch) -> None:
    win, store = _window(qapp, tmp_path, monkeypatch, [40, 5], enabled=True)
    try:
        assert [r.path for r in store.repos] == [str(tmp_path / "r1")]
        assert store.recent[0]["path"] == str(tmp_path / "r0")
    finally:
        win.close()


def test_expiry_off_removes_nothing(qapp, tmp_path, monkeypatch) -> None:
    win, store = _window(qapp, tmp_path, monkeypatch, [400], enabled=False)
    try:
        assert len(store.repos) == 1
    finally:
        win.close()


def test_row_with_terminal_never_expires(qapp, tmp_path, monkeypatch) -> None:
    win, store = _window(qapp, tmp_path, monkeypatch, [1], enabled=True, days=30)
    try:
        repo = store.repos[0]
        repo.last_used = time.time() - 90 * DAY
        win._terminals[repo.id] = object()   # stands in for a live TerminalHost
        win._expire_idle_rows()
        assert store.repos == [repo]
    finally:
        win._terminals.clear()
        win.close()


def test_load_without_last_used_counts_from_now(tmp_path: Path) -> None:
    path = tmp_path / "repos.json"
    path.write_text(json.dumps({"version": 1, "repos": [{"path": "/a", "id": "x"}]}))
    store = RepoStore(config_path=path)
    store.load()
    assert time.time() - store.repos[0].last_used < 60


def test_last_used_round_trips(tmp_path: Path) -> None:
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path="/a", last_used=1234.5)]
    store.save()
    again = RepoStore(config_path=tmp_path / "repos.json")
    again.load()
    assert again.repos[0].last_used == 1234.5


def test_mark_used_saves_at_most_hourly(tmp_path: Path) -> None:
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path="/a", last_used=1000.0)]
    rid = store.repos[0].id

    store.mark_used(rid, now=1000.0 + 60)
    assert store.repos[0].last_used == 1000.0
    assert not (tmp_path / "repos.json").exists()

    store.mark_used(rid, now=1000.0 + 3601)
    assert store.repos[0].last_used == 1000.0 + 3601
    assert (tmp_path / "repos.json").exists()


def test_settings_defaults() -> None:
    ui = UISettings()
    assert ui.expire_idle_repos is False
    assert ui.expire_idle_days == 30


def test_prefs_days_spinbox_greys_out_when_off(qapp, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    dlg = PreferencesDialog(Settings())
    assert dlg._expire_idle.isChecked() is False
    assert dlg._expire_days.isEnabled() is False
    dlg._expire_idle.setChecked(True)
    assert dlg._expire_days.isEnabled() is True
    dlg.close()
