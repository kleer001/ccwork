"""Top-strip tab above the terminal, showing the active `repo · branch`.

MainWindow places it over the terminal's sidebar-side corner. While a row is
current, it paints as a rounded tab in that row's accent, open at the bottom
where it meets the terminal frame (see current_highlight.py).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from src.ui.current_highlight import EDGE_W, Highlight

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

    def set_repo(self, name: str | None, branch: str | None = None) -> None:
        if not name:
            self._text = "ccwork"
        else:
            self._text = f"{name}  ·  {branch}" if branch else name
        self.update()

    def preferred_width(self) -> int:
        return self.fontMetrics().horizontalAdvance(self._text) + 2 * (PAD_X + EDGE_W)

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
        elided = self.fontMetrics().elidedText(self._text, Qt.ElideMiddle, text_rect.width())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)
        p.end()
