"""Empty-state placeholder shown when no terminal is current.

Two code paths land here: a cold start with no repos, and a terminal
exiting while it was the currently-displayed one. Today both leave the
user staring at a flat colored rectangle. This widget replaces it with
a centered ccwork logo + heading + version subhead + a static list of
hints pointing at the keyboard shortcuts and right-click menu.

Static by design. No dynamic per-state copy ("Add a repo to begin" vs
"Pick a repo from the sidebar"), no animations, no clickable hints.
Promote to buttons in a follow-up only if user feedback shows the text
hints get ignored.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


log = logging.getLogger(__name__)


# Match the bindings table in MainWindow._install_global_keys.
HINT_LINES = (
    "Press <b>Ctrl+Shift+O</b> to add a repo",
    "Right-click any repo for options",
    "Press <b>Ctrl+Shift+P</b> for preferences",
    "Press <b>F1</b> for keyboard shortcuts",
)


class EmptyState(QWidget):
    """Centered logo + heading + version + hints, theme-aware via palette.

    Construction is cheap and idempotent; safe to instantiate eagerly in
    `MainWindow.__init__` regardless of whether the user will ever see it.

    Attributes the tests rely on:
        ``_heading`` — the bold "ccwork" QLabel.
        ``_subhead`` — the version-and-tagline QLabel.
        ``_hints`` — list of hint QLabels; tests assert the count.
        ``_logo`` — the logo QLabel (may be hidden if loading failed).
    """

    LOGO_PX = 96

    def __init__(self, version: str, logo_path: Path | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Centered single column. Outer HBox + stretches → horizontal centering;
        # the inner VBox + stretches → vertical centering. Either axis collapses
        # gracefully on a too-small window (top/bottom stretches absorb to zero,
        # word-wrap on the labels handles narrow widths).
        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addStretch(1)
        column = QVBoxLayout()
        outer.addLayout(column, 0)
        outer.addStretch(1)

        column.addStretch(1)

        self._logo = QLabel(self)
        self._logo.setAlignment(Qt.AlignCenter)
        pixmap = self._render_logo(logo_path) if logo_path is not None else None
        if pixmap is not None and not pixmap.isNull():
            self._logo.setPixmap(pixmap)
        else:
            # Silent hide on missing/broken SVG per spec — the user resolved
            # this decision against a placeholder-icon fallback.
            self._logo.hide()
        column.addWidget(self._logo, 0, Qt.AlignCenter)

        self._heading = QLabel("ccwork", self)
        heading_font = QFont(self.font())
        heading_font.setPointSizeF(heading_font.pointSizeF() * 2.0)
        heading_font.setBold(True)
        self._heading.setFont(heading_font)
        self._heading.setAlignment(Qt.AlignCenter)
        column.addWidget(self._heading)

        self._subhead = QLabel(
            f"v{version} — embedded xterm sessions for Claude Code",
            self,
        )
        self._subhead.setAlignment(Qt.AlignCenter)
        self._subhead.setWordWrap(True)
        column.addWidget(self._subhead)

        column.addSpacing(12)

        self._hints: list[QLabel] = []
        for line in HINT_LINES:
            label = QLabel(line, self)
            label.setAlignment(Qt.AlignCenter)
            label.setTextFormat(Qt.RichText)
            label.setWordWrap(True)
            column.addWidget(label)
            self._hints.append(label)

        column.addStretch(1)

    def _render_logo(self, path: Path) -> QPixmap | None:
        """Rasterize the SVG to a square LOGO_PX pixmap. Returns None on
        any failure (file missing, QtSvg parse error, etc.) — caller hides
        the label silently per the spec."""
        try:
            if not path.exists():
                log.info("empty-state: logo %s not found — hiding image", path)
                return None
            renderer = QSvgRenderer(str(path))
            if not renderer.isValid():
                log.warning("empty-state: %s is not a valid SVG — hiding image", path)
                return None
            pixmap = QPixmap(QSize(self.LOGO_PX, self.LOGO_PX))
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            return pixmap
        except Exception as e:  # pragma: no cover — defensive against QtSvg
            log.warning("empty-state: logo render failed (%s) — hiding image", e)
            return None
