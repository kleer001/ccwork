"""Last-focused bookmark is storage-separate from Claude alerts.

The bookmark used to live in the same `_status` dict as done/attention,
which meant a Claude `Stop` event could overwrite a user bookmark via
`set_status`. It now lives in its own field (`_last_focused`) with its
own role (`ROLE_LAST_FOCUSED`) and paints a left-edge stripe in a
distinct code path. The badge column is reserved for genuine Claude
alerts.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.core.repo_store import Repo, RepoStore
from src.ui.repo_sidebar import (
    ROLE_LAST_FOCUSED,
    ROLE_STATUS,
    RepoDelegate,
    RepoListModel,
    STATUS_ATTENTION,
    STATUS_DONE,
)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _store_with(paths: list[str], cfg_path: Path) -> RepoStore:
    store = RepoStore(config_path=cfg_path)
    store.repos = [Repo(path=p) for p in paths]
    return store


def test_last_focused_not_in_right_edge_badge_dicts() -> None:
    """Only Claude alerts live in the right-edge dot/glyph dicts."""
    assert set(RepoDelegate.STATUS_COLORS) == {STATUS_DONE, STATUS_ATTENTION}
    assert set(RepoDelegate.STATUS_GLYPHS) == {STATUS_DONE, STATUS_ATTENTION}


def test_last_focused_stripe_color_is_subtle_per_theme() -> None:
    """The stripe pushes the base hue toward the row background — lighter
    on light themes, darker on dark themes — so it reads as ambient
    bookmark, not as a status alert."""
    from PySide6.QtGui import QColor, QPalette

    base = RepoDelegate.LAST_FOCUSED_BASE

    light = QPalette()
    light.setColor(QPalette.Base, QColor(255, 255, 255))
    light_color = RepoDelegate._last_focused_stripe_color(light)
    assert light_color.lightness() > base.lightness()

    dark = QPalette()
    dark.setColor(QPalette.Base, QColor(20, 20, 20))
    dark_color = RepoDelegate._last_focused_stripe_color(dark)
    assert dark_color.lightness() < base.lightness()


def test_claude_alert_does_not_clobber_last_focused_bookmark(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The whole reason we split the storage: a Claude Stop on the bookmarked
    row must not wipe the bookmark, and the bookmark must not block the
    alert from painting."""
    store = _store_with(["/a", "/b"], tmp_path / "repos.json")
    model = RepoListModel(store)

    model.set_last_focused("/a")
    assert model.index(0).data(ROLE_LAST_FOCUSED) is True

    # Claude alert lands on the bookmarked row.
    model.set_status("/a", STATUS_DONE)

    # Both signals coexist on the row, sourced from separate storage.
    assert model.index(0).data(ROLE_LAST_FOCUSED) is True
    assert model.index(0).data(ROLE_STATUS) == STATUS_DONE


def test_user_navigation_does_not_clobber_claude_alert(
    qapp: QApplication, tmp_path: Path
) -> None:
    """Inverse direction — set_last_focused must never touch _status."""
    store = _store_with(["/a", "/b"], tmp_path / "repos.json")
    model = RepoListModel(store)

    model.set_status("/a", STATUS_ATTENTION)
    model.set_last_focused("/a")

    assert model.index(0).data(ROLE_STATUS) == STATUS_ATTENTION
    assert model.index(0).data(ROLE_LAST_FOCUSED) is True


def test_set_last_focused_replaces_prior_bookmark(
    qapp: QApplication, tmp_path: Path
) -> None:
    """Only one row carries the bookmark at a time."""
    store = _store_with(["/a", "/b"], tmp_path / "repos.json")
    model = RepoListModel(store)

    model.set_last_focused("/a")
    assert model.index(0).data(ROLE_LAST_FOCUSED) is True
    assert model.index(1).data(ROLE_LAST_FOCUSED) is False

    model.set_last_focused("/b")
    assert model.index(0).data(ROLE_LAST_FOCUSED) is False
    assert model.index(1).data(ROLE_LAST_FOCUSED) is True


def test_set_last_focused_none_clears_bookmark(
    qapp: QApplication, tmp_path: Path
) -> None:
    store = _store_with(["/a"], tmp_path / "repos.json")
    model = RepoListModel(store)
    model.set_last_focused("/a")
    assert model.index(0).data(ROLE_LAST_FOCUSED) is True
    model.set_last_focused(None)
    assert model.index(0).data(ROLE_LAST_FOCUSED) is False
