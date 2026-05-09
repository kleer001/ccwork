"""Auto-arrange-by-recent-Claude-activity tests for RepoListModel.

The sidebar can optionally re-sort itself so the repos with the most
recent Claude-driven status changes (Stop / Notification /
UserPromptSubmit) bubble to the top. STATUS_LAST_FOCUSED is set by user
navigation, not Claude, and must not feed the sort.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from PySide6.QtCore import QPersistentModelIndex
from PySide6.QtWidgets import QApplication

from src.core.repo_store import Repo, RepoStore
from src.ui.repo_sidebar import (
    STATUS_ATTENTION,
    STATUS_DONE,
    STATUS_LAST_FOCUSED,
    RepoListModel,
)


def _store_with(paths: list[str], cfg_path: Path) -> RepoStore:
    store = RepoStore(config_path=cfg_path)
    store.repos = [Repo(path=p) for p in paths]
    return store


def _paths(model: RepoListModel) -> list[str]:
    return [r.path for r in model._store.repos]


def test_apply_auto_arrange_orders_by_recency_desc(
    qapp: QApplication, tmp_path: Path
) -> None:
    paths = ["/a", "/b", "/c", "/d"]
    store = _store_with(paths, tmp_path / "repos.json")
    model = RepoListModel(store)

    # Stamp activity in order: D first, then C, then B. A never stamped.
    model.set_status("/d", STATUS_DONE)
    model.set_status("/c", STATUS_DONE)
    model.set_status("/b", STATUS_ATTENTION)

    changed = model.apply_auto_arrange()
    assert changed
    # B is most recent → top, then C, D. A had no activity → stays at the
    # bottom in its original slot.
    assert _paths(model) == ["/b", "/c", "/d", "/a"]


def test_no_activity_repos_keep_stable_relative_order(
    qapp: QApplication, tmp_path: Path
) -> None:
    paths = ["/a", "/b", "/c", "/d"]
    store = _store_with(paths, tmp_path / "repos.json")
    model = RepoListModel(store)

    # Only B gets activity; A, C, D stay in their original relative order.
    model.set_status("/b", STATUS_DONE)

    model.apply_auto_arrange()
    assert _paths(model) == ["/b", "/a", "/c", "/d"]


def test_last_focused_does_not_stamp_activity(
    qapp: QApplication, tmp_path: Path
) -> None:
    paths = ["/a", "/b"]
    store = _store_with(paths, tmp_path / "repos.json")
    model = RepoListModel(store)

    # Only A gets a Claude-driven event.
    model.set_status("/a", STATUS_DONE)
    # Setting STATUS_LAST_FOCUSED on B is user navigation, not Claude.
    model.set_status("/b", STATUS_LAST_FOCUSED)

    assert model.last_activity("/a") > 0
    assert model.last_activity("/b") == 0.0

    model.apply_auto_arrange()
    # A bubbles to the top; B stays below it because B has no activity.
    assert _paths(model) == ["/a", "/b"]


def test_user_prompt_submit_stamps_activity(
    qapp: QApplication, tmp_path: Path
) -> None:
    paths = ["/a", "/b"]
    store = _store_with(paths, tmp_path / "repos.json")
    model = RepoListModel(store)

    # set_working(True) is the model-side effect of a UserPromptSubmit hook.
    model.set_working("/b", True)
    assert model.last_activity("/b") > 0

    model.apply_auto_arrange()
    assert _paths(model) == ["/b", "/a"]


def test_apply_auto_arrange_returns_false_when_order_unchanged(
    qapp: QApplication, tmp_path: Path
) -> None:
    paths = ["/a", "/b"]
    store = _store_with(paths, tmp_path / "repos.json")
    model = RepoListModel(store)

    # A is already first and gets the activity → order doesn't change.
    model.set_status("/a", STATUS_DONE)
    assert model.apply_auto_arrange() is False


def test_persistent_index_follows_row_after_reorder(
    qapp: QApplication, tmp_path: Path
) -> None:
    paths = ["/a", "/b", "/c"]
    store = _store_with(paths, tmp_path / "repos.json")
    model = RepoListModel(store)

    # Take a persistent index on row 2 (/c).
    pidx = QPersistentModelIndex(model.index(2))
    assert pidx.isValid() and pidx.row() == 2

    # Bump /c so it moves to the top.
    model.set_status("/c", STATUS_DONE)
    model.apply_auto_arrange()

    assert _paths(model)[0] == "/c"
    # The persistent index should now point at row 0 — same repo.
    assert pidx.isValid()
    assert pidx.row() == 0
