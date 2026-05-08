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
    # selection-change handler — bubble-up animation kicks off with one
    # immediate step; /b selection follows the row.
    sb._view.setCurrentIndex(sb._model.index(1))
    # First step has already swapped /c and /d.
    assert [r.path for r in sb._model._store.repos] == ["/a", "/b", "/d", "/c"]
    # Drive the animation to completion (stops itself when converged).
    while sb._step_arrange():
        pass
    assert sb._model._store.repos[0].path == "/d"
    cur_row = sb._view.currentIndex().row()
    assert sb._model._store.repos[cur_row].path == "/b"


def test_grouping_animation_walks_one_swap_per_step(
    qapp: QApplication, tmp_path: Path
) -> None:
    """Each step bubbles the topmost-target row up by exactly one position."""
    sb = _sidebar_with(
        ["/a", "/b", "/c", "/d", "/e"], tmp_path / "repos.json", group=True
    )
    ids = [r.id for r in sb._model._store.repos]

    # /e becomes active; nothing reshuffles yet.
    sb._view.setCurrentIndex(sb._model.index(4))
    sb.set_terminal_active(ids[4], True)
    sb._view.setCurrentIndex(sb._model.index(0))  # consume _regroup_pending

    # Selection-change ran one immediate step → /e is now at row 3.
    assert [r.path for r in sb._model._store.repos] == ["/a", "/b", "/c", "/e", "/d"]
    sb._step_arrange()
    assert [r.path for r in sb._model._store.repos] == ["/a", "/b", "/e", "/c", "/d"]
    sb._step_arrange()
    assert [r.path for r in sb._model._store.repos] == ["/a", "/e", "/b", "/c", "/d"]
    sb._step_arrange()
    assert [r.path for r in sb._model._store.repos] == ["/e", "/a", "/b", "/c", "/d"]
    # Converged — next step is a no-op and stops the timer.
    assert sb._step_arrange() is False
    assert sb._arrange_step_timer.isActive() is False


def test_grouping_animation_picks_up_new_active_mid_walk(
    qapp: QApplication, tmp_path: Path
) -> None:
    """A repo that becomes active mid-animation gets bubbled too — each tick
    recomputes the target, so new arrivals fall in line without restart."""
    sb = _sidebar_with(
        ["/a", "/b", "/c", "/d", "/e"], tmp_path / "repos.json", group=True
    )
    ids = [r.id for r in sb._model._store.repos]

    # /e active → click off → first step taken.
    sb._view.setCurrentIndex(sb._model.index(4))
    sb.set_terminal_active(ids[4], True)
    sb._view.setCurrentIndex(sb._model.index(0))
    assert [r.path for r in sb._model._store.repos] == ["/a", "/b", "/c", "/e", "/d"]

    # Mid-walk: /c also becomes active. Target now wants both /c and /e on top.
    # Tie-breaker is current row index (stable within the active group), so
    # /c (currently row 2) sorts above /e (currently row 3) and bubbles first.
    sb.set_terminal_active(ids[2], True)
    sb._step_arrange()
    assert [r.path for r in sb._model._store.repos] == ["/a", "/c", "/b", "/e", "/d"]
    sb._step_arrange()
    assert [r.path for r in sb._model._store.repos] == ["/c", "/a", "/b", "/e", "/d"]
    # /c is home; the loop now bubbles /e into row 1.
    sb._step_arrange()
    assert [r.path for r in sb._model._store.repos] == ["/c", "/a", "/e", "/b", "/d"]
    sb._step_arrange()
    assert [r.path for r in sb._model._store.repos] == ["/c", "/e", "/a", "/b", "/d"]
    assert sb._step_arrange() is False


def test_auto_arrange_uses_bubble_animation(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The activity-driven reorder (the one the user sees after a Claude
    turn) walks one swap per tick, just like the grouping reorder. This
    is the path that produced the instant 'pop to top' before the unified
    stepper landed.
    """
    cfg = tmp_path / "repos.json"
    store = RepoStore(config_path=cfg)
    settings = Settings(
        ui=UISettings(group_active_repos=False, auto_arrange_repos=True)
    )
    sb = RepoSidebar(store, settings=settings)
    sb._model.beginResetModel()
    store.repos = [Repo(path=p) for p in ["/a", "/b", "/c", "/d"]]
    sb._model.endResetModel()

    # /d gets fresh activity — auto-arrange wants it at row 0.
    sb._model.set_status("/d", STATUS_DONE)

    # Fire the debounce-end handler directly (skip the 2 s wait).
    sb._apply_auto_arrange()
    # First step ran inside _start_arrange_animation: /d moved from 3 → 2.
    assert [r.path for r in sb._model._store.repos] == ["/a", "/b", "/d", "/c"]
    sb._step_arrange()
    assert [r.path for r in sb._model._store.repos] == ["/a", "/d", "/b", "/c"]
    sb._step_arrange()
    assert [r.path for r in sb._model._store.repos] == ["/d", "/a", "/b", "/c"]
    assert sb._step_arrange() is False
