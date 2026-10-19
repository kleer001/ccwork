"""Tests for the current-row highlight shape (src/ui/current_highlight.py).

The shape is painted in segments by several widgets, so the tests grab real
renders and read pixels: the row edges, the open side, and the bridge across
the list frame must all agree. MainWindow tests cover when the highlight is
on and where the title tab sits.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from src.core.repo_store import Repo, RepoStore
from src.core.settings import Settings
from src.ui import badge_theme
from src.ui.current_highlight import EDGE_W, Highlight
from src.ui.qt_theme import blend
from src.ui.repo_sidebar import RepoSidebar
from tests.conftest import FakeHost, StubHookServer

ACCENT = QColor("#b58900")
TINT = QColor("#e9dcb0")


def _store(tmp_path: Path) -> RepoStore:
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path="/a", id="r-a"), Repo(path="/b", id="r-b"), Repo(path="/c", id="r-c")]
    store.save()  # the sidebar reloads the store from disk
    return store


def test_blend_is_an_opaque_mix() -> None:
    assert blend(QColor(0, 0, 0), QColor(200, 100, 0), 0.5) == QColor(100, 50, 0)
    assert blend(QColor(255, 255, 255), QColor(200, 100, 0), 0) == QColor(255, 255, 255)


def test_current_row_and_bridge_paint_one_shape(qapp: QApplication, tmp_path: Path) -> None:
    sidebar = RepoSidebar(_store(tmp_path))
    sidebar.resize(260, 400)
    sidebar.show()
    sidebar.select_id("r-b")
    qapp.processEvents()
    band = sidebar.current_row_band()
    assert band is not None
    sidebar.set_highlight(Highlight(ACCENT, TINT, "left", band, (0, 0)))
    img = sidebar.grab().toImage()

    view = sidebar._view
    vp_left = view.viewport().mapTo(sidebar, QPoint(0, 0)).x()
    frame_x = view.width() - view.frameWidth()       # the list frame, open side
    top, bottom = band
    mid = (top + bottom) // 2
    px = lambda x, y: img.pixelColor(x, y)
    assert px(vp_left + 40, top) == ACCENT                    # top edge
    assert px(vp_left + 40, bottom) == ACCENT                 # bottom edge
    assert px(vp_left, mid) == ACCENT                         # outer side edge
    assert px(vp_left + EDGE_W, mid + 20) == TINT             # fill
    assert px(frame_x - 1, mid + 20) == TINT                  # open side: no border
    assert px(frame_x, mid + 20) == TINT                      # bridge over the frame
    assert px(frame_x, top) == ACCENT                         # bridge edges line up
    assert px(frame_x, bottom) == ACCENT


def test_no_band_when_nothing_is_selected(qapp: QApplication, tmp_path: Path) -> None:
    sidebar = RepoSidebar(_store(tmp_path))
    assert sidebar.current_row_band() is None
    assert sidebar.current_row() == -1


@pytest.fixture
def win(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from src.ui.main_window import MainWindow
    w = MainWindow(store=_store(tmp_path), hook_server=StubHookServer(), settings=Settings())
    w.resize(1000, 600)
    w.show()
    host = FakeHost()
    w._terminals["r-c"] = host
    w._stack.addWidget(host)
    yield w
    w.close()


def test_highlight_follows_the_terminal(win, qapp: QApplication) -> None:
    win._sync_highlight()
    assert win._highlight is None                     # splash, nothing selected
    win._sidebar.select_id("r-c")
    qapp.processEvents()
    h = win._highlight
    assert h is not None
    assert h.accent == badge_theme.current_accent(2)  # third row
    assert h.band == win._sidebar.current_row_band()
    win._show_dashboard()
    qapp.processEvents()
    assert win._highlight is None                     # the overlay hides it


@pytest.mark.parametrize("side", ["left", "right"])
def test_title_tab_sits_on_the_terminal_corner(win, qapp: QApplication, side: str) -> None:
    win._settings.ui.sidebar_side = side
    win._apply_sidebar_layout()
    qapp.processEvents()
    left, right = win._place_title_tab()
    frame_left = win._frame.mapTo(win, QPoint(0, 0)).x()
    tab = win._title.geometry()
    assert tab.bottom() + 1 == win._title.parentWidget().height()   # sits on the frame
    assert win._title.parentWidget().mapTo(win, QPoint(0, 0)).y() + tab.bottom() + 1 \
        == win._frame.mapTo(win, QPoint(0, 0)).y()
    if side == "left":
        assert left == frame_left
    else:
        assert right == frame_left + win._frame.width() - 1


def test_sidebar_slot_never_exceeds_the_sidebar(qapp: QApplication, tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """A sidebar_width above the sidebar's maximum would leave a gap that
    breaks the bridge between the row and the splitter handle."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from src.ui.main_window import MainWindow
    settings = Settings()
    settings.ui.sidebar_width = 10_000
    w = MainWindow(store=_store(tmp_path), hook_server=StubHookServer(), settings=settings)
    w.resize(1000, 600)
    w.show()
    qapp.processEvents()
    assert w._splitter.sizes()[0] == w._sidebar.width()
    w.close()
