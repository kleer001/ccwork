"""apply_terminal_grouping floats active-terminal repos to the top.

Composes with the activity-based auto-arrange: grouping is the primary
key, recency the secondary one, so an inactive repo with very recent
activity still sorts below an active repo with none.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.core.repo_store import Repo, RepoStore
from src.core.settings import Settings, UISettings
from src.ui.repo_sidebar import STATUS_DONE, RepoListModel, RepoSidebar


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _store_with(paths: list[str], cfg_path: Path) -> RepoStore:
    store = RepoStore(config_path=cfg_path)
    store.repos = [Repo(path=p) for p in paths]
    return store


def _ids(model: RepoListModel) -> list[str]:
    return [r.id for r in model._store.repos]


def test_grouping_floats_active_repos_to_top(
    qapp: QApplication, tmp_path: Path
) -> None:
    store = _store_with(["/a", "/b", "/c", "/d"], tmp_path / "repos.json")
    model = RepoListModel(store)
    a, b, c, d = _ids(model)

    # B and D have a live terminal; A and C don't.
    model.set_terminal_active(b, True)
    model.set_terminal_active(d, True)

    assert model.apply_terminal_grouping() is True
    # Within each group, original order is preserved.
    assert _ids(model) == [b, d, a, c]


def test_grouping_returns_false_when_already_grouped(
    qapp: QApplication, tmp_path: Path
) -> None:
    store = _store_with(["/a", "/b"], tmp_path / "repos.json")
    model = RepoListModel(store)
    a, _b = _ids(model)
    model.set_terminal_active(a, True)

    # First call rearranges (or no-ops if already correct); second is a no-op.
    model.apply_terminal_grouping()
    assert model.apply_terminal_grouping() is False


def test_grouping_dominates_auto_arrange(
    qapp: QApplication, tmp_path: Path
) -> None:
    """Inactive repo with very recent activity still sorts below an active
    repo that has no activity at all."""
    store = _store_with(["/a", "/b"], tmp_path / "repos.json")
    model = RepoListModel(store)
    a, b = _ids(model)

    # A has fresh activity but no terminal. B has a terminal but no activity.
    model.set_status("/a", STATUS_DONE)
    model.set_terminal_active(b, True)

    # Activity-only sort would float A. Grouping applied afterward overrides.
    model.apply_auto_arrange()
    model.apply_terminal_grouping()
    assert _ids(model) == [b, a]


def _sidebar_with(paths: list[str], cfg_path: Path, *, group: bool) -> RepoSidebar:
    store = RepoStore(config_path=cfg_path)
    settings = Settings(ui=UISettings(group_active_repos=group))
    sb = RepoSidebar(store, settings=settings)
    sb._model.beginResetModel()
    store.repos = [Repo(path=p) for p in paths]
    sb._model.endResetModel()
    return sb


def test_set_terminal_active_does_not_reshuffle_immediately(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The just-activated row must stay put until the user moves off it.

    Reshuffling under the cursor reads as 'the wrong repo got selected'
    even when persistent indexes preserve the logical selection.
    """
    sb = _sidebar_with(
        ["/a", "/b", "/c", "/d"], tmp_path / "repos.json", group=True
    )
    ids = [r.id for r in sb._model._store.repos]

    # Simulate clicking /d: select it, then mark its terminal active.
    sb._view.setCurrentIndex(sb._model.index(3))
    pre = [r.path for r in sb._model._store.repos]
    sb.set_terminal_active(ids[3], True)
    post = [r.path for r in sb._model._store.repos]
    assert pre == post, "set_terminal_active must defer the reshuffle"
    # And the selection is still /d at row 3.
    assert sb._view.currentIndex().row() == 3
    assert sb._model._store.repos[3].path == "/d"


def test_pending_regroup_fires_on_next_selection_change(
    qapp: QApplication, tmp_path: Path
) -> None:
    sb = _sidebar_with(
        ["/a", "/b", "/c", "/d"], tmp_path / "repos.json", group=True
    )
    ids = [r.id for r in sb._model._store.repos]

    # User clicks /d; terminal spawns; reshuffle is deferred.
    sb._view.setCurrentIndex(sb._model.index(3))
    sb.set_terminal_active(ids[3], True)
    assert [r.path for r in sb._model._store.repos] == ["/a", "/b", "/c", "/d"]

    # User clicks /b. The deferred regroup fires at the start of the
    # selection-change handler; /d floats to the top, /b selection follows.
    sb._view.setCurrentIndex(sb._model.index(1))
    assert sb._model._store.repos[0].path == "/d"
    cur_row = sb._view.currentIndex().row()
    assert sb._model._store.repos[cur_row].path == "/b"
