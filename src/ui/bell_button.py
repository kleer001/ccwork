"""Top-bar 🔔 toolbutton with a small red corner dot when unseen alerts exist.

Pure visual widget — owns its own paint pass. `MainWindow` calls
`set_unseen(True)` when an idle hook event arrives and `set_unseen(False)`
on click; the bell aggregates across repos and carries no per-repo state.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QToolButton


class BellButton(QToolButton):
    """🔔 toolbutton with a small red dot in the corner when unseen alerts exist."""

    DOT_COLOR = QColor(220, 80, 80)
    DOT_D = 7

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setText("🔔")
        self.setAutoRaise(True)
        self._unseen = False

    def set_unseen(self, on: bool) -> None:
        if on != self._unseen:
            self._unseen = on
            self.update()

    def paintEvent(self, ev) -> None:  # type: ignore[override]
        super().paintEvent(ev)
        if not self._unseen:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(self.DOT_COLOR)
        d = self.DOT_D
        p.drawEllipse(self.width() - d - 2, 2, d, d)
