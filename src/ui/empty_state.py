"""Empty-state / splash placeholder shown when no terminal is current.

Two code paths land here: a cold start with no repo selected, and a
terminal exiting while it was the currently-displayed one. The widget
shows a centered ccwork logo + heading + version subhead + a fixed list
of keyboard/right-click hints, then a live "git pulse" bento: a hero
tile with the week's commit total and a Monday-anchored bar chart
(weekday letters, y-axis gridlines; days after today render blank so the
chart never changes width), a repos count, the list of repos with
uncommitted changes, the most-recent commit, and a rotating tip.

The git stats are gathered off the GUI thread (a `_StatsWorker` QThread)
each time the splash is shown — git forks would otherwise jank the UI —
and the tiles fill in when the worker returns. The whole bento stays
hidden until there's something to show, so a no-repos cold start still
reads as a clean onboarding screen. Stats are opt-in: with no
`repos_provider` the widget is exactly the static logo+hints screen.

Accent colors come from `badge_theme` (the app's theming source); card
fills are translucent overlays so they read on any palette.
"""

from __future__ import annotations

import logging
import math
from itertools import cycle
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from src.core.repo_stats import RepoStats, gather_stats, relative_time
from src.ui.badge_theme import (
    AMBIENT_COLOR, SPINNER_COLOR, STATUS_COLORS, STATUS_DONE, SUBAGENT_COLOR,
)


log = logging.getLogger(__name__)


# Match the bindings table in MainWindow._install_global_keys.
HINT_LINES = (
    "Press <b>Ctrl+Shift+O</b> to add a repo",
    "Right-click any repo for options",
    "Press <b>Ctrl+Shift+P</b> for preferences",
    "Press <b>F1</b> for keyboard shortcuts",
)

# Lesser-known features cycled one-at-a-time under the static hints.
TIP_LINES = (
    "Tip: <b>Ctrl+Tab</b> cycles between repos",
    "Tip: <b>Ctrl+Shift+1…9</b> jumps straight to a sidebar row",
    "Tip: hold <b>Ctrl</b> and press +/− to zoom the terminal",
    "Tip: drag the sidebar splitter to resize — it remembers the width",
    "Tip: right-click a repo → <b>Set badge…</b> to tag it with an emoji",
    "Tip: right-click a repo → <b>Rebind to…</b> if you moved its folder",
    "Tip: active repos float to the top of the sidebar automatically",
    "Tip: uncheck <b>Restore last repo</b> in preferences to always land here",
)

TIP_INTERVAL_MS = 7000

# Monday-first weekday initials, indexed by date.weekday() (0=Mon … 6=Sun).
WEEK_LETTERS = ("M", "T", "W", "T", "F", "S", "S")

# Bento accents (sourced from the app theme; orange has no theme knob).
_ACCENT_REPOS = SPINNER_COLOR
_ACCENT_CHART = SUBAGENT_COLOR
_ACCENT_RECENT = STATUS_COLORS[STATUS_DONE]
_ACCENT_DIRTY = QColor("#cb4b16")   # solarized orange
_MUTED = AMBIENT_COLOR


def _qss_card(overlay_rgb: str, radius: int = 12, alpha: float = 0.07) -> str:
    return (f"QFrame{{background-color: rgba({overlay_rgb},{alpha});"
            f" border-radius:{radius}px;}}")


class BarChart(QWidget):
    """Rounded Monday-anchored week bar chart: y-axis gridlines + numbers
    on the left, weekday letters under each bar. Days after `today_idx`
    render as faint letters with no bar, so the chart is always 7 wide."""

    L_PAD, B_PAD, T_PAD, R_PAD = 22, 16, 6, 2

    def __init__(self, accent: QColor, muted: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._counts: list[int] = [0] * len(WEEK_LETTERS)
        self._today_idx = len(WEEK_LETTERS) - 1
        self._accent = accent
        self._muted = muted
        self.setMinimumHeight(118)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, counts: list[int], today_idx: int) -> None:
        self._counts = list(counts)
        self._today_idx = today_idx
        self.update()

    def _nice_top(self) -> tuple[int, int]:
        hi = max(self._counts) if self._counts else 1
        hi = hi or 1
        step = max(1, math.ceil(hi / 4))
        return step * 4, step

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        plot_w = w - self.L_PAD - self.R_PAD
        plot_h = h - self.T_PAD - self.B_PAD
        top_val, step = self._nice_top()

        grid = QColor(self._muted); grid.setAlpha(70)
        gfont = QFont(self.font()); gfont.setPointSizeF(7.0)
        for t in range(0, top_val + 1, step):
            y = self.T_PAD + plot_h - (t / top_val) * plot_h
            p.setPen(grid)
            p.drawLine(self.L_PAD, int(y), w - self.R_PAD, int(y))
            p.setFont(gfont); p.setPen(self._muted)
            p.drawText(QRectF(0, y - 7, self.L_PAD - 4, 14),
                       Qt.AlignRight | Qt.AlignVCenter, str(t))

        n = len(self._counts)
        gap = 7
        bw = (plot_w - gap * (n - 1)) / n
        hi = max(self._counts) if self._counts else 0
        faint = QColor(self._muted); faint.setAlpha(110)
        lfont = QFont(self.font()); lfont.setPointSizeF(8.0); lfont.setBold(True)
        for i, c in enumerate(self._counts):
            x = self.L_PAD + i * (bw + gap)
            bh = (c / top_val) * plot_h
            if bh > 0:
                bar = QPainterPath()
                bar.addRoundedRect(QRectF(x, self.T_PAD + plot_h - bh, bw, bh), 4, 4)
                col = QColor(self._accent)
                if c == hi:
                    col = col.lighter(118)
                p.fillPath(bar, col)
            if i > self._today_idx:
                pen = faint
            elif i == self._today_idx:
                pen = self._accent
            else:
                pen = self._muted
            p.setFont(lfont); p.setPen(pen)
            p.drawText(QRectF(x, h - self.B_PAD, bw, self.B_PAD),
                       Qt.AlignCenter, WEEK_LETTERS[i])
        p.end()


class EmptyState(QWidget):
    """Centered logo + heading + version + hints + a live git-pulse bento.

    Construction is cheap and idempotent; safe to instantiate eagerly in
    `MainWindow.__init__` regardless of whether the user will ever see it.

    Attributes the tests rely on:
        ``_heading`` — the bold "ccwork" QLabel.
        ``_subhead`` — the version-and-tagline QLabel.
        ``_hints`` — list of hint QLabels; tests assert the count.
        ``_logo`` — the logo QLabel (may be hidden if loading failed).
        ``_pulse`` — the bento container (hidden until stats arrive).
        ``_chart`` / ``_week_total`` / ``_repos_num`` / ``_dirty_num`` /
        ``_recent`` / ``_tip`` — the populated stat widgets.
    """

    LOGO_PX = 96

    def __init__(self, version: str, logo_path: Path | None = None,
                 parent: QWidget | None = None,
                 repos_provider: Callable[[], list[tuple[str, str]]] | None = None) -> None:
        super().__init__(parent)
        self._repos_provider = repos_provider
        self._worker: _StatsWorker | None = None
        self._tips = cycle(TIP_LINES)
        self._txt = self.palette().color(QPalette.WindowText)
        # Card fills are a translucent overlay over the window bg. White
        # lightens a dark theme; black darkens a light one — so the boxes
        # read either way. Pick the direction from the bg's lightness.
        bg = self.palette().color(QPalette.Window)
        self._overlay = "0,0,0" if bg.lightnessF() > 0.5 else "255,255,255"
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

        column.addSpacing(16)
        self._pulse = self._build_pulse()
        self._pulse.hide()
        column.addWidget(self._pulse, 0, Qt.AlignHCenter)

        column.addSpacing(12)

        # Rotating tip cycles independently of the git sweep.
        self._tip = QLabel(self)
        self._tip.setAlignment(Qt.AlignCenter)
        self._tip.setTextFormat(Qt.RichText)
        self._tip.setWordWrap(True)
        tip_font = QFont(self.font())
        tip_font.setPointSizeF(tip_font.pointSizeF() * 1.15)
        self._tip.setFont(tip_font)
        column.addWidget(self._tip)
        self._next_tip()

        self._tip_timer = QTimer(self)
        self._tip_timer.setInterval(TIP_INTERVAL_MS)
        self._tip_timer.timeout.connect(self._next_tip)

        column.addStretch(1)

    # ── bento construction ──

    def _label(self, text: str = "", *, color: QColor | None = None, pt: float = 10.0,
               bold: bool = False, upper: bool = False, spacing: float = 0.0,
               align=Qt.AlignLeft) -> QLabel:
        lbl = QLabel(text, self)
        f = QFont(self.font())
        f.setPointSizeF(pt)
        f.setBold(bold)
        if upper:
            f.setCapitalization(QFont.AllUppercase)
        if spacing:
            f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
        lbl.setFont(f)
        lbl.setStyleSheet(f"color:{(color or self._txt).name()}; background:transparent;")
        lbl.setAlignment(align)
        return lbl

    def _card(self, radius: int = 12, alpha: float = 0.07) -> QFrame:
        f = QFrame(self)
        f.setStyleSheet(_qss_card(self._overlay, radius, alpha))
        return f

    def _build_pulse(self) -> QWidget:
        """The git-pulse bento. Builds the tile skeleton; values land in
        `_apply_stats`."""
        root = QWidget(self)
        root.setFixedWidth(440)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(10)

        # hero: week total + bar chart
        hero = self._card(14, 0.10)
        hv = QVBoxLayout(hero); hv.setContentsMargins(16, 12, 16, 12); hv.setSpacing(6)
        htop = QHBoxLayout(); htop.setSpacing(8)
        self._week_total = self._label("0", color=_ACCENT_CHART, pt=30, bold=True)
        cap = self._label("commits\nthis week", color=_MUTED, pt=8.5, upper=True, spacing=1.0)
        htop.addWidget(self._week_total); htop.addWidget(cap); htop.addStretch(1)
        hv.addLayout(htop)
        self._chart = BarChart(_ACCENT_CHART, _MUTED, hero)
        hv.addWidget(self._chart)
        grid.addWidget(hero, 0, 0, 2, 1)

        # repos tile
        repos = self._card(12)
        rv = QVBoxLayout(repos); rv.setContentsMargins(12, 10, 12, 8); rv.setSpacing(0)
        self._repos_num = self._label("0", color=_ACCENT_REPOS, pt=22, bold=True)
        rv.addWidget(self._repos_num)
        rv.addWidget(self._label("repos", color=_MUTED, pt=8.5, upper=True, spacing=1.0))
        grid.addWidget(repos, 0, 1)

        # uncommitted tile (number + listed repo names)
        dirty = self._card(12)
        dv = QVBoxLayout(dirty); dv.setContentsMargins(12, 10, 12, 10); dv.setSpacing(0)
        dtop = QHBoxLayout(); dtop.setSpacing(6)
        self._dirty_num = self._label("0", color=_MUTED, pt=22, bold=True)
        dtop.addWidget(self._dirty_num)
        dtop.addWidget(self._label("uncommitted", color=_MUTED, pt=8.5, upper=True, spacing=1.0))
        dtop.addStretch(1)
        dv.addLayout(dtop)
        self._dirty_names_lay = QVBoxLayout(); self._dirty_names_lay.setSpacing(0)
        self._dirty_name_labels: list[QLabel] = []
        dv.addLayout(self._dirty_names_lay)
        grid.addWidget(dirty, 1, 1)

        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        v.addLayout(grid)

        # footer: latest commit
        foot = self._card(12)
        fv = QVBoxLayout(foot); fv.setContentsMargins(14, 9, 14, 9); fv.setSpacing(1)
        self._recent = self._label("", color=_ACCENT_RECENT, pt=9.5)
        self._recent.setWordWrap(True)
        self._recent_age = self._label("", color=_MUTED, pt=8.5)
        fv.addWidget(self._recent); fv.addWidget(self._recent_age)
        self._recent_card = foot
        v.addWidget(foot)
        return root

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

    # ── stats + tips lifecycle ──

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._tip_timer.start()
        self.refresh_stats()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._tip_timer.stop()

    def refresh_stats(self) -> None:
        """Re-gather git stats on a worker thread. No-op without a provider
        or while a prior sweep is still running."""
        if self._repos_provider is None:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        repos = self._repos_provider()
        self._worker = _StatsWorker(repos, self)
        self._worker.done.connect(self._apply_stats)
        self._worker.start()

    def _apply_stats(self, stats: RepoStats) -> None:
        if stats.repo_count == 0:
            self._pulse.hide()
            return

        self._week_total.setText(str(stats.commits_this_week))
        self._chart.set_data(stats.daily_counts, stats.today_index)
        self._repos_num.setText(str(stats.repo_count))

        self._dirty_num.setText(str(stats.dirty_count))
        self._dirty_num.setStyleSheet(
            f"color:{(_ACCENT_DIRTY if stats.dirty_count else _MUTED).name()};"
            " background:transparent;"
        )
        for lbl in self._dirty_name_labels:
            self._dirty_names_lay.removeWidget(lbl)
            lbl.deleteLater()
        self._dirty_name_labels = []
        for name in stats.dirty_names:
            lbl = self._label(f"• {name}", color=self._txt, pt=9)
            self._dirty_names_lay.addWidget(lbl)
            self._dirty_name_labels.append(lbl)

        if stats.recent is not None:
            self._recent.setText(f"● {stats.recent.name} — “{stats.recent.subject}”")
            self._recent_age.setText(relative_time(stats.recent.ts))
            self._recent_card.show()
        else:
            self._recent_card.hide()

        self._pulse.show()

    def _next_tip(self) -> None:
        self._tip.setText(next(self._tips))


class _StatsWorker(QThread):
    """Runs `gather_stats` on a worker thread and emits the result.

    Owned by the EmptyState; short-lived (one git sweep per show)."""

    done = Signal(object)  # RepoStats

    def __init__(self, repos: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._repos = repos

    def run(self) -> None:  # pragma: no cover — exercised via live runs, not offscreen
        try:
            stats = gather_stats(self._repos)
        except Exception as e:
            log.warning("repo_stats worker failed: %s", e)
            return
        self.done.emit(stats)
