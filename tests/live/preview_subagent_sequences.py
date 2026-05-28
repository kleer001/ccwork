#!/usr/bin/env python3
"""Side-by-side live preview of two candidate subagent-twinkle sequences.

Shows the 11 approved glyphs animating as two different orderings — a
random shuffle vs a light→heavy→light bloom — at the real twinkle rate
(1/SUBAGENT_SLOWDOWN of the spinner rate), each beside an animating braille
spinner so the pairing matches a real sidebar row. Pick whichever reads as
the calmest bloom.

Not a pytest test (off the *_test.py glob). Needs a real X11/XWayland
display. Run directly:

    .venv/bin/python tests/live/preview_subagent_sequences.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import Qt, QRect, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.ui.badge_theme import SPINNER_VARIANTS, SUBAGENT_COLOR
from src.ui.qt_theme import build_palette
from src.core.settings import load_settings

BADGE_COL_W = 16
SUBAGENT_SLOWDOWN = 3

# Light → heavy → light bloom: ascending visual weight, then back down
# (peak and trough not repeated) so consecutive frames stay similar.
_ASCENDING = ["✲", "✵", "✷", "✱", "❂", "✹", "✺", "✸", "❉", "❊", "❋"]
BLOOM = _ASCENDING + _ASCENDING[-2:0:-1]

# A fixed shuffle of the same 11 glyphs.
RANDOM = ["❊", "✱", "✺", "✵", "❋", "✸", "✲", "❂", "✹", "✷", "❉"]


class SeqPreview(QWidget):
    """One animated column: big crosshair glyph + actual-size spinner pair."""

    def __init__(self, sequence: list[str], base: QColor, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(200, 260)
        self.seq = sequence
        self._base = base
        self.frame = 0
        self._spin = SPINNER_VARIANTS[0]

    def tick(self) -> None:
        self.frame += 1
        self.update()

    def _glyph(self) -> str:
        return self.seq[(self.frame // SUBAGENT_SLOWDOWN) % len(self.seq)]

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), self._base)
        text_color = self.palette().text().color()
        glyph = self._glyph()

        # actual-size strip: spinner outboard, candidate inboard
        row_h = 52
        top = 16
        right = self.width() - 24
        font = QFont(self.font())
        font.setPointSizeF(self.font().pointSizeF() * 1.4)
        font.setBold(True)
        p.setFont(font)
        spin = self._spin[self.frame % len(self._spin)]
        out = QRect(right - BADGE_COL_W, top, BADGE_COL_W, row_h)
        p.setPen(QPen(QColor("#268bd2")))
        p.drawText(out, Qt.AlignRight | Qt.AlignVCenter, spin)
        inb = QRect(right - 2 * BADGE_COL_W, top, BADGE_COL_W, row_h)
        p.setPen(QPen(SUBAGENT_COLOR))
        p.drawText(inb, Qt.AlignHCenter | Qt.AlignVCenter, glyph)
        guide = QPen(QColor(text_color.red(), text_color.green(), text_color.blue(), 60), 1)
        p.setPen(guide)
        p.drawRect(inb.adjusted(0, 0, -1, -1))

        # big crosshair view
        big_top = top + row_h + 8
        big_h = self.height() - big_top - 8
        big_w = big_h
        bx = (self.width() - big_w) // 2
        box = QRect(bx, big_top, big_w, big_h)
        p.setPen(guide)
        p.drawRect(box)
        cx, cy = box.center().x(), box.center().y()
        p.drawLine(cx, box.top(), cx, box.bottom())
        p.drawLine(box.left(), cy, box.right(), cy)
        bf = QFont(self.font())
        bf.setPointSizeF(big_h * 0.55)
        bf.setBold(True)
        p.setFont(bf)
        p.setPen(QPen(SUBAGENT_COLOR))
        p.drawText(box, Qt.AlignHCenter | Qt.AlignVCenter, glyph)


def _column(title: str, preview: SeqPreview) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    label = QLabel(title)
    label.setAlignment(Qt.AlignCenter)
    f = label.font()
    f.setBold(True)
    label.setFont(f)
    lay.addWidget(label)
    lay.addWidget(preview, 1)
    return w


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    settings = load_settings()
    pal = build_palette(settings.xterm)
    base = pal.base().color()

    win = QWidget()
    win.setPalette(pal)
    win.setWindowTitle("Subagent sequence preview")
    win.resize(480, 320)

    rand = SeqPreview(RANDOM, base)
    bloom = SeqPreview(BLOOM, base)

    lay = QHBoxLayout(win)
    lay.addWidget(_column("Random order", rand))
    lay.addWidget(_column("Light → heavy → light", bloom))

    timer = QTimer(win)
    timer.setInterval(settings.ui.animation.spinner_interval_ms)
    timer.timeout.connect(rand.tick)
    timer.timeout.connect(bloom.tick)
    timer.start()

    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
