"""set_terminal_active toggles ROLE_HAS_TERMINAL per repo id.

Drives the bold-upright / regular-italic split in the delegate so the user
can see which repos already have a live terminal this session. Per-id (not
per-path) so duplicate rows track independently.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.core.repo_store import Repo, RepoStore
from src.ui.repo_sidebar import ROLE_HAS_TERMINAL, RepoListModel


def _store_with_duplicates(path: str, cfg_path: Path) -> RepoStore:
    store = RepoStore(config_path=cfg_path)
    store.add(path)
    store.add(path)
    return store


def test_default_is_inactive(qapp: QApplication, tmp_path: Path) -> None:
    real = tmp_path / "repo"
    real.mkdir()
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.add(str(real))
    model = RepoListModel(store)
    assert model.index(0).data(ROLE_HAS_TERMINAL) is False


def test_set_active_lights_only_matching_id(
    qapp: QApplication, tmp_path: Path
) -> None:
    """Two duplicate rows on the same path must track independently — opening
    one terminal does not unitalicize the other."""
    real = tmp_path / "repo"
    real.mkdir()
    store = _store_with_duplicates(str(real), tmp_path / "repos.json")
    model = RepoListModel(store)

    first_id = store.repos[0].id
    second_id = store.repos[1].id

    model.set_terminal_active(first_id, True)
    assert model.index(0).data(ROLE_HAS_TERMINAL) is True
    assert model.index(1).data(ROLE_HAS_TERMINAL) is False

    model.set_terminal_active(second_id, True)
    assert model.index(1).data(ROLE_HAS_TERMINAL) is True


def test_clearing_active_reverts_role(qapp: QApplication, tmp_path: Path) -> None:
    real = tmp_path / "repo"
    real.mkdir()
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.add(str(real))
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.set_terminal_active(rid, True)
    model.set_terminal_active(rid, False)
    assert model.index(0).data(ROLE_HAS_TERMINAL) is False


def test_unknown_id_is_noop(qapp: QApplication, tmp_path: Path) -> None:
    """Calling set_terminal_active with an id no longer in the store (row
    just removed) must not raise — it just no-ops."""
    store = RepoStore(config_path=tmp_path / "repos.json")
    model = RepoListModel(store)
    model.set_terminal_active("nonexistent", True)
    model.set_terminal_active("nonexistent", False)
