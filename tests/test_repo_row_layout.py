"""Three-line sidebar row: `_repo_line` line-2 fit and delegate painting.

Painting goes into a QImage with a real RepoListModel index, so the test
exercises the same data roles the sidebar reads. Pixel comparisons check
that the title and status line are drawn, not only that paint() returns.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFont, QFontMetrics, QImage, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from src.core.hook_server import EVENT_USER_PROMPT_SUBMIT
from src.core.repo_store import Repo, RepoStore
from src.core.settings import LayoutSettings
from src.ui.repo_delegate import RepoDelegate, _repo_line
from src.ui.repo_model import RepoListModel
from src.ui.badge_theme import STATUS_DONE


@pytest.fixture
def fm(qapp: QApplication) -> QFontMetrics:
    return QFontMetrics(QFont())


# ── _repo_line ──


def test_repo_line_fits_whole(fm: QFontMetrics) -> None:
    full = "garden | main"
    assert _repo_line(fm, "garden", "main", fm.horizontalAdvance(full) + 20) == full


def test_repo_line_branch_elides_before_name(fm: QFontMetrics) -> None:
    name, branch = "garden", "feature/a-very-long-branch-name"
    width = fm.horizontalAdvance("garden | ") + fm.horizontalAdvance("feat")
    line = _repo_line(fm, name, branch, width)

    assert line.startswith("garden | ")
    assert line.endswith("…")
    assert line != f"{name} | {branch}"
    assert fm.horizontalAdvance(line) <= width


def test_repo_line_shows_name_alone_when_no_branch_room(fm: QFontMetrics) -> None:
    name = "garden"
    width = fm.horizontalAdvance(name)
    assert _repo_line(fm, name, "main", width) == name


def test_repo_line_without_branch_is_the_name(fm: QFontMetrics) -> None:
    assert _repo_line(fm, "garden (II)", "", 500) == "garden (II)"


def test_repo_line_elides_a_name_too_wide_for_the_width(fm: QFontMetrics) -> None:
    line = _repo_line(fm, "a-very-long-repository-name", "", 40)
    assert line.endswith("…")
    assert fm.horizontalAdvance(line) <= 40


# ── delegate paint and sizeHint ──


def _model(tmp_path: Path, title: str = "", emoji: str = "") -> RepoListModel:
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path=str(tmp_path / "garden"), title=title, emoji=emoji)]
    return RepoListModel(store)


def _option(width: int = 260, height: int = 66) -> QStyleOptionViewItem:
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, width, height)
    opt.font = QFont()
    opt.palette = QPalette()
    opt.state = QStyle.StateFlag.State_None
    return opt


def _paint(delegate: RepoDelegate, model: RepoListModel) -> QImage:
    opt = _option()
    img = QImage(opt.rect.width(), opt.rect.height(), QImage.Format.Format_ARGB32)
    img.fill(Qt.white)
    painter = QPainter(img)
    try:
        delegate.paint(painter, opt, model.index(0))
    finally:
        painter.end()
    return img


def test_title_line_is_painted(qapp: QApplication, tmp_path: Path) -> None:
    untitled = _paint(RepoDelegate(), _model(tmp_path / "a", title=""))
    titled = _paint(RepoDelegate(), _model(tmp_path / "b", title="fix login bug"))
    assert titled != untitled


def test_status_line_is_painted_when_on(qapp: QApplication, tmp_path: Path) -> None:
    model = _model(tmp_path)
    model.set_status(model._store.repos[0].id, STATUS_DONE)
    delegate = RepoDelegate()
    delegate.show_status_text = True
    on = _paint(delegate, model)
    delegate.show_status_text = False
    off = _paint(delegate, model)
    assert on != off


def test_paint_with_status_text_off_has_no_error(qapp: QApplication, tmp_path: Path) -> None:
    model = _model(tmp_path, title="fix login bug")
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, model._store.repos[0].id)
    delegate = RepoDelegate()
    delegate.show_status_text = False
    assert not _paint(delegate, model).isNull()


def test_size_hint_covers_three_lines_when_row_height_is_small(
    qapp: QApplication, tmp_path: Path
) -> None:
    model = _model(tmp_path)
    delegate = RepoDelegate(layout=LayoutSettings(row_height=10))
    opt = _option()
    opt.font = QFont()
    opt.font.setPointSize(14)
    h = delegate.sizeHint(opt, model.index(0)).height()
    assert h >= 3 * QFontMetrics(opt.font).height()


def test_size_hint_keeps_configured_row_height_when_larger(
    qapp: QApplication, tmp_path: Path
) -> None:
    model = _model(tmp_path)
    delegate = RepoDelegate(layout=LayoutSettings(row_height=200))
    assert delegate.sizeHint(_option(), model.index(0)).height() == 200
