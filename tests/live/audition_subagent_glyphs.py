#!/usr/bin/env python3
"""Live WYSIWYG auditioning rig for the subagent-twinkle glyphs.

Paints each candidate exactly as RepoDelegate does — solarized-cyan, bold,
font scaled 1.4x, centred in a BADGE_COL_W cell — sitting one slot inboard
of an animating braille spinner, on the app's base palette colour. Centre
crosshairs over the inboard cell make vertical/horizontal misalignment
obvious at a glance.

Controls:
  ◀ / ▶  or  Left / Right   — previous / next candidate
  👍  or  Up                 — keep current glyph
  👎  or  Down               — drop current glyph
The kept list (in audition order) is shown live at the bottom and printed
to stdout on each change, ready to paste into badges.toml's subagent_frames
or _DEFAULTS in src/ui/badge_theme.py.

Not a pytest test (name is off the *_test.py glob). Needs a real X11/XWayland
display. Run directly:

    .venv/bin/python tests/live/audition_subagent_glyphs.py
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import Qt, QRect, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.badge_theme import SPINNER_VARIANTS, SUBAGENT_COLOR
from src.ui.qt_theme import build_palette  # type: ignore
from src.core.settings import load_settings


# Candidate pool: the star/asterisk family that renders as a single centred
# cell. Order is the audition order, not a final sequence.
CANDIDATES = [
    "✦",  # ✦ current
    "✶",  # ✶ current
    "✷",  # ✷ current
    "❋",  # ❋ current
    "✱",  # ✱
    "✲",  # ✲
    "✳",  # ✳
    "✴",  # ✴
    "✵",  # ✵
    "✸",  # ✸
    "✹",  # ✹
    "✺",  # ✺
    "❂",  # ❂
    "❉",  # ❉
    "❊",  # ❊
    "∗",  # ∗ asterisk operator
    "＊",  # ＊ fullwidth asterisk
]

BADGE_COL_W = 16  # mirrors RepoDelegate.BADGE_COL_W


def _name(ch: str) -> str:
    try:
        return unicodedata.name(ch)
    except ValueError:
        return "<unnamed>"


class Preview(QWidget):
    """Paints the actual-size delegate strip plus a zoomed crosshair view."""

    def __init__(self, palette_base: QColor, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self._base = palette_base
        self.glyph = CANDIDATES[0]
        self.spinner_frame = 0
        # First braille variant as the reference spinner.
        self._spin = SPINNER_VARIANTS[0]

    def set_glyph(self, glyph: str) -> None:
        self.glyph = glyph
        self.update()

    def tick(self) -> None:
        self.spinner_frame += 1
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), self._base)
        text_color = self.palette().text().color()

        # ── actual-size delegate strip ──
        # Lay out exactly like a sidebar row's right edge: outboard braille
        # spinner, inboard candidate. row_h taken from settings so the cell
        # proportions match the real delegate.
        row_h = 52
        strip_top = 20
        strip_right = self.width() - 30
        font = QFont(self.font())
        font.setPointSizeF(self.font().pointSizeF() * 1.4)
        font.setBold(True)
        p.setFont(font)

        # outboard: spinner (solarized blue-ish; reuse text color tint)
        spin_glyph = self._spin[self.spinner_frame % len(self._spin)]
        out_rect = QRect(strip_right - BADGE_COL_W, strip_top, BADGE_COL_W, row_h)
        p.setPen(QPen(QColor("#268bd2")))
        p.drawText(out_rect, Qt.AlignRight | Qt.AlignVCenter, spin_glyph)

        # inboard: candidate (subagent cyan), centred in its cell
        in_rect = QRect(strip_right - 2 * BADGE_COL_W, strip_top, BADGE_COL_W, row_h)
        p.setPen(QPen(SUBAGENT_COLOR))
        p.drawText(in_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.glyph)

        # cell guides for the inboard slot so misalignment is obvious
        guide = QPen(QColor(text_color.red(), text_color.green(), text_color.blue(), 60), 1)
        p.setPen(guide)
        p.drawRect(in_rect.adjusted(0, 0, -1, -1))
        cx = in_rect.center().x()
        cy = in_rect.center().y()
        p.drawLine(cx, in_rect.top(), cx, in_rect.bottom())
        p.drawLine(in_rect.left(), cy, in_rect.right(), cy)

        p.setPen(QPen(text_color))
        small = QFont(self.font())
        small.setPointSizeF(self.font().pointSizeF() * 0.8)
        p.setFont(small)
        p.drawText(
            QRect(20, strip_top, strip_right - 2 * BADGE_COL_W - 30, row_h),
            Qt.AlignRight | Qt.AlignVCenter,
            "actual size  →",
        )

        # ── zoomed crosshair view ──
        big_top = strip_top + row_h + 10
        big_h = self.height() - big_top - 10
        big_w = big_h
        big_x = (self.width() - big_w) // 2
        big_rect = QRect(big_x, big_top, big_w, big_h)
        p.setPen(QPen(QColor(text_color.red(), text_color.green(), text_color.blue(), 60), 1))
        p.drawRect(big_rect)
        bcx = big_rect.center().x()
        bcy = big_rect.center().y()
        p.drawLine(bcx, big_rect.top(), bcx, big_rect.bottom())
        p.drawLine(big_rect.left(), bcy, big_rect.right(), bcy)

        big_font = QFont(self.font())
        big_font.setPointSizeF(big_h * 0.55)
        big_font.setBold(True)
        p.setFont(big_font)
        p.setPen(QPen(SUBAGENT_COLOR))
        p.drawText(big_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.glyph)


class Rig(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Subagent glyph audition")
        self.resize(420, 460)

        settings = load_settings()
        pal = build_palette(settings.xterm)
        self.setPalette(pal)
        base = pal.base().color()

        self.idx = 0
        self.kept: list[str] = []

        self.preview = Preview(base, self)

        self.info = QLabel(self)
        self.info.setAlignment(Qt.AlignCenter)

        self.kept_label = QLabel(self)
        self.kept_label.setWordWrap(True)
        self.kept_label.setAlignment(Qt.AlignCenter)

        prev_btn = QPushButton("<", self)
        next_btn = QPushButton(">", self)
        drop_btn = QPushButton("👎 No thanks", self)
        keep_btn = QPushButton("👍 Approve", self)
        prev_btn.clicked.connect(self.prev)
        next_btn.clicked.connect(self.next)
        keep_btn.clicked.connect(self.keep)
        drop_btn.clicked.connect(self.drop)
        keep_btn.setStyleSheet("background-color: #859900; color: white; font-weight: bold;")
        drop_btn.setStyleSheet("background-color: #dc322f; color: white; font-weight: bold;")

        btns = QHBoxLayout()
        # Nav pair sits together on the left; verdict pair on the right.
        btns.addWidget(prev_btn)
        btns.addWidget(next_btn)
        btns.addStretch(1)
        btns.addWidget(drop_btn)
        btns.addWidget(keep_btn)

        lay = QVBoxLayout(self)
        lay.addWidget(self.preview, 1)
        lay.addWidget(self.info)
        lay.addLayout(btns)
        lay.addWidget(QLabel("Kept (audition order):", self))
        lay.addWidget(self.kept_label)

        self.timer = QTimer(self)
        self.timer.setInterval(settings.ui.animation.spinner_interval_ms)
        self.timer.timeout.connect(self.preview.tick)
        self.timer.start()

        self._refresh()

    def _refresh(self) -> None:
        ch = CANDIDATES[self.idx]
        self.preview.set_glyph(ch)
        verdict = "KEPT" if ch in self.kept else ""
        self.info.setText(
            f"{self.idx + 1}/{len(CANDIDATES)}   {ch}   "
            f"U+{ord(ch):04X}   {_name(ch)}   {verdict}"
        )
        self.kept_label.setText(
            "  ".join(self.kept) + (f"\n\n{self.kept!r}" if self.kept else "—")
        )
        print(f"kept = {self.kept!r}", flush=True)

    def prev(self) -> None:
        self.idx = (self.idx - 1) % len(CANDIDATES)
        self._refresh()

    def next(self) -> None:
        self.idx = (self.idx + 1) % len(CANDIDATES)
        self._refresh()

    def keep(self) -> None:
        ch = CANDIDATES[self.idx]
        if ch not in self.kept:
            self.kept.append(ch)
        self.next()

    def drop(self) -> None:
        ch = CANDIDATES[self.idx]
        if ch in self.kept:
            self.kept.remove(ch)
        self.next()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        k = e.key()
        if k == Qt.Key_Left:
            self.prev()
        elif k == Qt.Key_Right:
            self.next()
        elif k == Qt.Key_Up:
            self.keep()
        elif k == Qt.Key_Down:
            self.drop()
        else:
            super().keyPressEvent(e)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    rig = Rig()
    rig.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
