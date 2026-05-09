"""Shared fixtures + factories for the test suite.

Replaces the qapp / _store_with / _sidebar_with copies that lived in
each test file. Test files just take the fixtures they need; they no
longer need their own QT_QPA_PLATFORM bootstrap or fixture definitions.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Force offscreen Qt before any PySide import in any test module. Tests
# that need a different platform can override via QT_QPA_PLATFORM env
# in their own test runner config.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.core.repo_store import Repo, RepoStore


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Session-scoped QApplication. PySide6 allows only one per process —
    re-using it across tests is required, not just an optimization."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_store(tmp_path: Path):
    """Factory: build a RepoStore at a tmp config path.

    Usage:
        store = make_store(["/a", "/b"])
        store = make_store(["/path"], duplicates=2)  # /path twice
    """
    def _make(paths: list[str], *, duplicates: int = 1) -> RepoStore:
        store = RepoStore(config_path=tmp_path / "repos.json")
        for p in paths:
            for _ in range(duplicates):
                store.add(p)
        return store
    return _make


@pytest.fixture
def make_store_raw(tmp_path: Path):
    """Factory: build a RepoStore with `Repo` objects directly (no add()).

    Used by tests that want to bypass `add`'s realpath-resolution and
    instance-numbering — e.g. checking how the model handles paths that
    don't exist on disk.
    """
    def _make(paths: list[str]) -> RepoStore:
        store = RepoStore(config_path=tmp_path / "repos.json")
        store.repos = [Repo(path=p) for p in paths]
        return store
    return _make
