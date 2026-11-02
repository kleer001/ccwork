"""Three-line sidebar row: `fit_line` line-2 fit and delegate painting.

Painting goes into a QImage with a real RepoListModel index, so the test
exercises the same data roles the sidebar reads. Pixel comparisons check
that the title and status line are drawn, not only that paint() returns.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFont, QFontMetrics, QFontMetricsF, QImage, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from src.core.hook_server import EVENT_USER_PROMPT_SUBMIT
from src.core.repo_store import Repo, RepoStore
from src.core.settings import RowLineSettings, RowSettings
from src.ui.repo_delegate import LINE_HEIGHT, REPO_LINE_SEP, RepoDelegate, fit_line, line_slots
from src.ui.repo_model import RepoListModel
from src.ui.badge_theme import STATUS_DONE


@pytest.fixture
def fm(qapp: QApplication) -> QFontMetrics:
    return QFontMetrics(QFont())


# ── fit_line ──


def test_repo_line_fits_whole(fm: QFontMetrics) -> None:
    full = f"garden{REPO_LINE_SEP}main"
    assert fit_line(fm, "garden", "main", fm.horizontalAdvance(full) + 20) == full


def test_repo_line_branch_elides_before_name(fm: QFontMetrics) -> None:
    name, branch = "garden", "feature/a-very-long-branch-name"
    width = fm.horizontalAdvance(f"garden{REPO_LINE_SEP}") + fm.horizontalAdvance("feat")
    line = fit_line(fm, name, branch, width)

    assert line.startswith(f"garden{REPO_LINE_SEP}")
    assert line.endswith("…")
    assert line != f"{name}{REPO_LINE_SEP}{branch}"
    assert fm.horizontalAdvance(line) <= width


def test_repo_line_shows_name_alone_when_no_branch_room(fm: QFontMetrics) -> None:
    name = "garden"
    # horizontalAdvance rounds; elidedText measures the fractional width, so
    # the smallest width that holds the name is its true width rounded up.
    width = math.ceil(QFontMetricsF(QFont()).horizontalAdvance(name))
    assert fit_line(fm, name, "main", width) == name


def test_repo_line_without_branch_is_the_name(fm: QFontMetrics) -> None:
    assert fit_line(fm, "garden (II)", "", 500) == "garden (II)"


def test_repo_line_elides_a_name_too_wide_for_the_width(fm: QFontMetrics) -> None:
    line = fit_line(fm, "a-very-long-repository-name", "", 40)
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


def test_size_hint_is_the_configured_row_height(qapp: QApplication, tmp_path: Path) -> None:
    model = _model(tmp_path)
    delegate = RepoDelegate(rows=RowSettings(height=90))
    assert delegate.sizeHint(_option(), model.index(0)).height() == 90


def test_paints_every_line_style(qapp: QApplication, tmp_path: Path) -> None:
    line = RowLineSettings(underline=True, strike=True, highlight=True, highlight_color="accent",
                           caps=True, color="#336699", opacity=50, tracking=2.0, family="Liberation Serif")
    rows = RowSettings(layout="packed", order=["status", "repo", "title"],
                       title=line, repo=RowLineSettings(small_caps=True, color="muted"),
                       status=RowLineSettings(color="accent", highlight=True))
    model = _model(tmp_path, title="fix login bug")
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, model._store.repos[0].id)
    assert not _paint(RepoDelegate(rows=rows), model).isNull()


# ── line_slots ──


def _rows(layout: str, sizes=(12.0, 14.0, 12.0), **kw) -> RowSettings:
    title, repo, status = (RowLineSettings(size=s) for s in sizes)
    return RowSettings(height=70, inset=4, layout=layout, title=title, repo=repo, status=status, **kw)


def test_equal_layout_splits_the_height_in_thirds() -> None:
    scale, slots = line_slots(_rows("equal"), ["title", "repo", "status"])
    assert scale == 1.0
    assert [round(t, 3) for _, t, _ in slots] == [0, round(62 / 3, 3), round(124 / 3, 3)]


def test_sized_layout_gives_each_line_its_share() -> None:
    scale, slots = line_slots(_rows("sized"), ["repo", "title", "status"])
    assert scale == 1.0
    heights = [h for _, _, h in slots]
    assert abs(sum(heights) - 62) < 1e-9
    assert heights[0] > heights[1] == heights[2]


def test_packed_layout_centers_the_block_with_gaps() -> None:
    scale, slots = line_slots(_rows("packed", gap=3), ["title", "repo", "status"])
    block = sum(h for _, _, h in slots) + 2 * 3
    assert scale == 1.0
    assert abs(slots[0][1] - (62 - block) / 2) < 1e-9


def test_text_shrinks_when_the_lines_overflow_the_height() -> None:
    rows = _rows("sized", sizes=(30.0, 30.0, 30.0))
    scale, _ = line_slots(rows, ["title", "repo", "status"])
    assert abs(scale - 62 / (90 * LINE_HEIGHT)) < 1e-9
