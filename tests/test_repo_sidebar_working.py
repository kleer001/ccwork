"""Working-flag tests for duplicate rows.

`_working` is keyed by repo id, so each row owns its spinner. Two rows that
share one path (Ctrl+O on the same repo) must not share a spinner.
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


def test_working_on_one_duplicate_row_does_not_light_the_other(
    qapp: QApplication, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path=str(repo)), Repo(path=str(repo))]
    model = RepoListModel(store)
    first, second = (r.id for r in store.repos)

    model.set_working(first, True)
    assert model.index(0).data(ROLE_WORKING) is True
    assert model.index(1).data(ROLE_WORKING) is False

    model.set_working(second, True)
    model.set_working(first, False)
    assert model.index(0).data(ROLE_WORKING) is False
    assert model.index(1).data(ROLE_WORKING) is True
