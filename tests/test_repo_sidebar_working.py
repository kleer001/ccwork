"""Regression tests for the working-flag path-normalization bug.

Symptom: after starting a Claude turn (UserPromptSubmit), clicking off the
working repo would show its purple "last focused" dot instead of the spinner,
and the spinner never came back. Root cause: `_working` was a string-keyed
set, and a hook reporting cwd via a symlink path didn't match the
realpath-stored Repo.path in `data(ROLE_WORKING)`. Fix: normalize at every
boundary that touches `_working`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.core.repo_store import Repo, RepoStore
from src.ui.repo_sidebar import ROLE_WORKING, RepoListModel


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _store_with(repo_path: str, cfg_path: Path) -> RepoStore:
    store = RepoStore(config_path=cfg_path)
    store.repos = [Repo(path=repo_path)]
    return store


def test_set_working_via_symlink_path_lights_up_realpath_row(
    qapp: QApplication, tmp_path: Path
) -> None:
    real = tmp_path / "real_repo"
    real.mkdir()
    link = tmp_path / "link_repo"
    link.symlink_to(real)

    # Repo in the store as the realpath (matches RepoStore.add behavior).
    store = _store_with(str(real), tmp_path / "repos.json")
    model = RepoListModel(store)

    # Hook reports the symlink path. Pre-fix this would silently no-op.
    model.set_working(str(link), True)

    idx = model.index(0)
    assert idx.data(ROLE_WORKING) is True


def test_set_working_via_trailing_slash_matches(
    qapp: QApplication, tmp_path: Path
) -> None:
    real = tmp_path / "repo"
    real.mkdir()

    store = _store_with(str(real), tmp_path / "repos.json")
    model = RepoListModel(store)

    model.set_working(str(real) + "/", True)
    assert model.index(0).data(ROLE_WORKING) is True

    # And clearing via the canonical path still discards.
    model.set_working(str(real), False)
    assert model.index(0).data(ROLE_WORKING) is False


def test_clearing_working_via_different_path_shape_still_clears(
    qapp: QApplication, tmp_path: Path
) -> None:
    real = tmp_path / "r"
    real.mkdir()
    link = tmp_path / "l"
    link.symlink_to(real)

    store = _store_with(str(real), tmp_path / "repos.json")
    model = RepoListModel(store)

    model.set_working(str(real), True)
    assert model.index(0).data(ROLE_WORKING) is True

    # Stop hook arrives via the symlink — must still clear.
    model.set_working(str(link), False)
    assert model.index(0).data(ROLE_WORKING) is False
