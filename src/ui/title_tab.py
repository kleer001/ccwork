"""Top-strip tab above the terminal, showing the active `repo · branch · title`
(`main ↳ branch · title` for a worktree row). The title elides first and
drops out when no character of it fits.

MainWindow places it over the terminal's sidebar-side corner. While a row is
current, it paints as a rounded tab in that row's accent, open at the bottom
where it meets the terminal frame (see current_highlight.py).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from src.ui.current_highlight import EDGE_W, Highlight
from src.ui.repo_delegate import REPO_LINE_SEP, WORKTREE_LINE_SEP, fit_line

PAD_X = 14
RADIUS = 8


class TitleTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        self.setFont(f)
        self._highlight: Highlight | None = None
        self.set_repo(None, None)

    def set_repo(self, name: str | None, branch: str | None = None, title: str = "",
                 worktree: bool = False) -> None:
        if not name:
            self._head, self._title = "ccwork", ""
        else:
            sep = WORKTREE_LINE_SEP if worktree else REPO_LINE_SEP
            self._head = f"{name}{sep}{branch}" if branch else name
            self._title = title
        self.update()

    def preferred_width(self) -> int:
        text = f"{self._head}{REPO_LINE_SEP}{self._title}" if self._title else self._head
        # Round the fractional width up: elidedText measures fractions, so a
        # tab cut to the rounded-down width would elide its last character.
        width = math.ceil(QFontMetricsF(self.font()).horizontalAdvance(text))
        return width + 2 * (PAD_X + EDGE_W)

    def set_highlight(self, h: Highlight | None) -> None:
        self._highlight = h
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        h = self._highlight
        if h is not None:
            # Rounded rects taller than the widget: the clip cuts off their
            # bottom corners, so only the top corners round and the bottom
            # stays open into the frame.
            p.setRenderHint(QPainter.Antialiasing)
            w, ht = self.width(), self.height()
            outer = QPainterPath()
            outer.addRoundedRect(QRectF(0, 0, w, ht + RADIUS), RADIUS, RADIUS)
            inner = QPainterPath()
            r = max(RADIUS - EDGE_W, 0)
            inner.addRoundedRect(QRectF(EDGE_W, EDGE_W, w - 2 * EDGE_W, ht + RADIUS), r, r)
            p.fillPath(outer, h.accent)
            p.fillPath(inner, h.tint)
        text_rect = self.rect().adjusted(EDGE_W + PAD_X, EDGE_W, -(EDGE_W + PAD_X), 0)
        p.setPen(self.palette().text().color())
        text = fit_line(self.fontMetrics(), self._head, self._title, text_rect.width())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()
