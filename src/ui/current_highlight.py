"""Current-row highlight: one accent shape from the selected sidebar row to
the terminal it shows.

The shape crosses several widgets, so each one paints its own segment from
one shared `Highlight`:
  • RepoDelegate — the row: tint fill, accent edges on the top, the bottom
    and the outer side. The side that faces the terminal stays open.
  • RepoListView — the list's frame beside that row.
  • BridgeHandle — the splitter handle between the list and the terminal.
  • CurrentFrame — the accent edge along the terminal's top and sidebar
    side, open where the bridge and the title tab meet it.
  • TitleTab (title_tab.py) — the rounded tab above the terminal.
A transparent overlay cannot draw the shape: TerminalHost is a native X
window, and Qt makes the siblings of a native widget native too, so an
overlay would turn into an opaque window. Every segment maps the band from
window coordinates, so the edges meet to the pixel.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPoint, QRect
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QListView, QSplitter, QSplitterHandle, QVBoxLayout, QWidget

# Width (px) of every accent edge in the shape.
EDGE_W = 3


@dataclass(frozen=True)
class Highlight:
    accent: QColor
    tint: QColor
    # Side of the terminal the sidebar is on: "left" or "right".
    sidebar_side: str
    # Top and bottom y (inclusive, window coordinates) of the current row.
    # None when the bridge cannot reach the row: the row is not fully
    # visible, or the list's scroll bar stands between the row and the frame.
    band: tuple[int, int] | None
    # Left and right x (inclusive, window coordinates) of the title tab.
    tab: tuple[int, int]


def _local_band(widget: QWidget, h: Highlight) -> tuple[int, int]:
    top = widget.mapFrom(widget.window(), QPoint(0, h.band[0])).y()
    return top, top + h.band[1] - h.band[0]


def paint_band(painter: QPainter, x: int, width: int, top: int, bottom: int, h: Highlight) -> None:
    """The bridge cross-section: accent edge, tint, accent edge."""
    painter.fillRect(QRect(x, top, width, EDGE_W), h.accent)
    painter.fillRect(QRect(x, top + EDGE_W, width, bottom - top + 1 - 2 * EDGE_W), h.tint)
    painter.fillRect(QRect(x, bottom - EDGE_W + 1, width, EDGE_W), h.accent)


def paint_row(painter: QPainter, rect: QRect, h: Highlight) -> None:
    """The current row: the band plus an accent edge on the outer side."""
    paint_band(painter, rect.left(), rect.width(), rect.top(), rect.bottom(), h)
    x = rect.left() if h.sidebar_side == "left" else rect.right() - EDGE_W + 1
    painter.fillRect(QRect(x, rect.top(), EDGE_W, rect.height()), h.accent)


class RepoListView(QListView):
    """QListView that paints the bridge across its own frame. Reads the
    highlight from its delegate (RepoDelegate.highlight)."""

    def event(self, e) -> bool:  # type: ignore[override]
        # The frame is painted by QAbstractScrollArea.event, not paintEvent
        # (that one paints the viewport), so draw over it after the default.
        handled = super().event(e)
        if e.type() != QEvent.Paint:
            return handled
        h = self.itemDelegate().highlight
        if h is not None and h.band is not None:
            fw = self.frameWidth()
            x = self.width() - fw if h.sidebar_side == "left" else 0
            top, bottom = _local_band(self, h)
            p = QPainter(self)
            paint_band(p, x, fw, top, bottom, h)
            p.end()
        return handled


class BridgeHandle(QSplitterHandle):
    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        h = self.splitter().highlight
        if h is None or h.band is None:
            return
        top, bottom = _local_band(self, h)
        p = QPainter(self)
        paint_band(p, 0, self.width(), top, bottom, h)
        p.end()


class BridgeSplitter(QSplitter):
    """QSplitter whose handle carries the bridge."""

    def __init__(self, orientation, parent=None) -> None:
        super().__init__(orientation, parent)
        self.highlight: Highlight | None = None

    def createHandle(self) -> QSplitterHandle:  # type: ignore[override]
        return BridgeHandle(self.orientation(), self)

    def set_highlight(self, h: Highlight | None) -> None:
        self.highlight = h
        for i in range(self.count()):
            self.handle(i).update()


class CurrentFrame(QWidget):
    """Holds the terminal stack inside an accent edge on its top and its
    sidebar side. The margins stay when no row is current, so switching to
    the splash does not shift the terminal."""

    def __init__(self, child: QWidget, parent=None) -> None:
        super().__init__(parent)
        self._highlight: Highlight | None = None
        self._lay = QVBoxLayout(self)
        self._lay.setSpacing(0)
        self._lay.addWidget(child)

    def set_sidebar_side(self, side: str) -> None:
        if side == "left":
            self._lay.setContentsMargins(EDGE_W, EDGE_W, 0, 0)
        else:
            self._lay.setContentsMargins(0, EDGE_W, EDGE_W, 0)

    def set_highlight(self, h: Highlight | None) -> None:
        self._highlight = h
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        h = self._highlight
        if h is None:
            return
        p = QPainter(self)
        x = 0 if h.sidebar_side == "left" else self.width() - EDGE_W
        p.fillRect(QRect(0, 0, self.width(), EDGE_W), h.accent)
        p.fillRect(QRect(x, 0, EDGE_W, self.height()), h.accent)
        if h.band is not None:
            top, bottom = _local_band(self, h)
            p.fillRect(QRect(x, top + EDGE_W, EDGE_W, bottom - top + 1 - 2 * EDGE_W), h.tint)
        left = self.mapFrom(self.window(), QPoint(h.tab[0], 0)).x()
        p.fillRect(QRect(left + EDGE_W, 0, h.tab[1] - h.tab[0] + 1 - 2 * EDGE_W, EDGE_W), h.tint)
        p.end()
