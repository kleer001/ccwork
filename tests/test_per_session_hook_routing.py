"""Per-session hook routing.

When the hook payload carries a `repo_id` (stamped via CCWORK_REPO_ID by
terminal_session.build_session), the hook handler scopes state changes
to that single duplicate instead of broadcasting on cwd. Without it,
every duplicate row sharing a path would flip the spinner together.

Back-compat: when `repo_id` is missing or empty, the handler falls back
to cwd-broadcast (legacy hooks; shells spawned before the field was
added).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.core.hook_server import (
    EVENT_NOTIFICATION,
    EVENT_STOP,
    EVENT_USER_PROMPT_SUBMIT,
    HookServer,
)
from src.core.repo_store import RepoStore
from src.core.settings import Settings
from src.core.terminal_session import build_session
from src.ui.main_window import MainWindow
from src.ui.repo_sidebar import ROLE_STATUS, ROLE_WORKING, STATUS_ATTENTION


def _make_window(
    real_path: Path, cfg_path: Path, qapp: QApplication
) -> tuple[MainWindow, RepoStore]:
    store = RepoStore(config_path=cfg_path)
    # Two repos for the same path → two ids; the duplicate is the
    # whole point of the per-session routing tests below.
    store.add(str(real_path))
    store.add(str(real_path))
    # MainWindow's sidebar calls model.reload() in __init__, which reads
    # from disk — persist before constructing so the duplicates survive.
    store.save()
    # HookServer is constructed but not started — we only need the signal.
    hook_server = HookServer(parent=None)
    settings = Settings()
    win = MainWindow(store=store, hook_server=hook_server, settings=settings)
    return win, store


def test_build_session_stamps_repo_id_in_env(tmp_path: Path) -> None:
    """terminal_session injects CCWORK_REPO_ID so the hook sink can echo it."""
    store = RepoStore(config_path=tmp_path / "repos.json")
    repo = store.add(str(tmp_path))
    spec = build_session(repo)
    assert spec.env.get("CCWORK_REPO_ID") == repo.id


def test_repo_id_routes_to_one_duplicate_only(
    qapp: QApplication, tmp_path: Path
) -> None:
    real = tmp_path / "repo"
    real.mkdir()
    win, store = _make_window(real, tmp_path / "repos.json", qapp)
    try:
        a, b = store.repos[0], store.repos[1]
        # Hook arrives carrying a's id only — only a's row should spin.
        win._on_hook_event({
            "event": EVENT_USER_PROMPT_SUBMIT,
            "cwd": str(real),
            "repo_id": a.id,
        })
        model = win._sidebar.model
        idx_a = model.index(model.index_of_id(a.id))
        idx_b = model.index(model.index_of_id(b.id))
        assert idx_a.data(ROLE_WORKING) is True
        assert idx_b.data(ROLE_WORKING) is False

        # Stop on a's id — only a clears.
        win._on_hook_event({
            "event": EVENT_STOP,
            "cwd": str(real),
            "repo_id": a.id,
        })
        assert idx_a.data(ROLE_WORKING) is False
        assert idx_b.data(ROLE_WORKING) is False
    finally:
        win.close()


def test_missing_repo_id_falls_back_to_broadcast(
    qapp: QApplication, tmp_path: Path
) -> None:
    """Legacy hooks (no repo_id field) broadcast across all duplicates."""
    real = tmp_path / "repo"
    real.mkdir()
    win, store = _make_window(real, tmp_path / "repos.json", qapp)
    try:
        a, b = store.repos[0], store.repos[1]
        win._on_hook_event({
            "event": EVENT_USER_PROMPT_SUBMIT,
            "cwd": str(real),
            # no repo_id
        })
        model = win._sidebar.model
        idx_a = model.index(model.index_of_id(a.id))
        idx_b = model.index(model.index_of_id(b.id))
        assert idx_a.data(ROLE_WORKING) is True
        assert idx_b.data(ROLE_WORKING) is True
    finally:
        win.close()


def test_empty_repo_id_string_falls_back_to_broadcast(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The hook sink emits "" when CCWORK_REPO_ID is unset; treat as absent."""
    real = tmp_path / "repo"
    real.mkdir()
    win, store = _make_window(real, tmp_path / "repos.json", qapp)
    try:
        a, b = store.repos[0], store.repos[1]
        win._on_hook_event({
            "event": EVENT_USER_PROMPT_SUBMIT,
            "cwd": str(real),
            "repo_id": "",
        })
        model = win._sidebar.model
        assert model.index(model.index_of_id(a.id)).data(ROLE_WORKING) is True
        assert model.index(model.index_of_id(b.id)).data(ROLE_WORKING) is True
    finally:
        win.close()


def test_status_still_broadcasts_under_per_session_routing(
    qapp: QApplication, tmp_path: Path
) -> None:
    """Spinner state (_working) routes per-id; status badge does not.

    Documents a deliberate scope limitation in REFACTORING.md 1.2:
    `_status` remains path-keyed and broadcasts to every duplicate row
    even when the hook supplies a repo_id. Making status per-instance
    is tracked as future work.

    This test pins the current behavior so a future change to
    per-instance status will fail loudly here and force a deliberate
    update.
    """
    real = tmp_path / "repo"
    real.mkdir()
    win, store = _make_window(real, tmp_path / "repos.json", qapp)
    try:
        a, b = store.repos[0], store.repos[1]
        win._on_hook_event({
            "event": EVENT_NOTIFICATION,
            "cwd": str(real),
            "repo_id": a.id,
        })
        model = win._sidebar.model
        # Both rows share the path → both get the status badge.
        assert model.index(model.index_of_id(a.id)).data(ROLE_STATUS) == STATUS_ATTENTION
        assert model.index(model.index_of_id(b.id)).data(ROLE_STATUS) == STATUS_ATTENTION
    finally:
        win.close()
