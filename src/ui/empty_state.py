"""Empty-state / splash-dashboard shown when no terminal is current.

Three code paths land here: a cold start with no repo selected, a
terminal exiting while it was the currently-displayed one, and the
sidebar's Dashboard button. With no repos the widget is a clean
onboarding screen (logo + heading + hints). Once repos exist it becomes
the weekly-retro dashboard mirrored on ``mockups/dashboard.html``:

  1. narrative sentence first (deterministic template NLG) + freshness
  2. 8-week trend hero — commits per trailing week, this week highlighted
  3. week-in-numbers facts row (demoted, small)
  4. a single green release-celebration callout (the ONE bright moment)
  5. per-repo bento cards — radar fingerprint + stat ladder + tempo badge
  6. quiet strip — repos with no commits in 7 days, lifetime size

All stats are rolling 7-day windows, merges excluded, gathered off the
GUI thread (a `_StatsWorker` QThread) on every show and re-swept every
STATS_REFRESH_MS while visible — repos are live and a frozen number
reads as wrong within minutes. Stats are opt-in: with no
`repos_provider` the widget is exactly the static logo+hints screen.

Accent colors come from `badge_theme` (the app's theming source); card
fills are translucent overlays so they read on any palette. A dip is
muted grey, never red; green is reserved for the release celebration.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from itertools import cycle
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPalette, QPen,
    QPixmap, QPolygonF,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from src.core.repo_stats import (
    RADAR_AXES, RepoStats, RepoWeek, churn_tag, fingerprints, gather_stats,
    relative_time, summarize,
)
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
STATS_REFRESH_MS = 60_000     # re-sweep while visible — the board says "live"

DASH_W = 850                  # dashboard column width (mirrors the mockup's 900px wrap)

# Dashboard accents (sourced from the app theme where a knob exists).
_ACCENT_NEW = SPINNER_COLOR                  # new-work blue; radar fingerprint hue
_ACCENT_TREND = SUBAGENT_COLOR               # this-week highlight (cyan)
_ACCENT_GREEN = STATUS_COLORS[STATUS_DONE]   # THE celebration accent
_ACCENT_DIRTY = QColor("#cb4b16")            # solarized orange (crash banner)
_DEL_COLOR = QColor("#c98a5e")               # churn deletions — muted, not alarm
_MUTED = AMBIENT_COLOR


def _blend(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def _knum(n: int) -> str:
    """17_412 → '17.4k', 950 → '950'."""
    if abs(n) < 1000:
        return str(n)
    s = f"{n / 1000:.1f}k"
    return s.replace(".0k", "k")


class RadarChart(QWidget):
    """Six-spoke radar "fingerprint" (axes = RADAR_AXES, values 0..1).

    Mirrors the mockup's SVG math: grid rings at 0.5/1.0, spokes, small
    mono axis labels, a single-hue data polygon with vertex dots. The
    silhouette carries the meaning, not color — every card uses the same
    hue so shapes compare."""

    CX, CY, R = 66.0, 68.0, 42.0
    FLOOR = 0.05

    def __init__(self, accent: QColor, text: QColor, faint: QColor,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: tuple[float, ...] = (0.0,) * len(RADAR_AXES)
        self._accent = accent
        self._text = text
        self._faint = faint
        self.setFixedSize(QSize(132, 138))

    def set_values(self, values) -> None:
        vals = [max(0.0, min(1.0, float(v))) for v in values][:len(RADAR_AXES)]
        vals += [0.0] * (len(RADAR_AXES) - len(vals))
        self._values = tuple(vals)
        self.update()

    def _pt(self, i: int, r: float) -> QPointF:
        a = -math.pi / 2 + i * (math.pi / 3)      # start at top, clockwise
        return QPointF(self.CX + math.cos(a) * r, self.CY + math.sin(a) * r)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(RADAR_AXES)

        ring = QColor(self._text); ring.setAlpha(26)
        spoke = QColor(self._text); spoke.setAlpha(20)
        for f in (0.5, 1.0):
            p.setPen(QPen(ring, 1))
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(QPolygonF([self._pt(i, self.R * f) for i in range(n)]))
        p.setPen(QPen(spoke, 1))
        for i in range(n):
            p.drawLine(QPointF(self.CX, self.CY), self._pt(i, self.R))

        f = QFont("monospace"); f.setPointSizeF(6.5)
        p.setFont(f); p.setPen(self._faint)
        for i, name in enumerate(RADAR_AXES):
            c = self._pt(i, self.R + 11)
            p.drawText(QRectF(c.x() - 20, c.y() - 6, 40, 12), Qt.AlignCenter, name)

        pts = [self._pt(i, self.R * (self.FLOOR + (1 - self.FLOOR) * v))
               for i, v in enumerate(self._values)]
        fill = QColor(self._accent); fill.setAlpha(41)   # 0.16
        pen = QPen(self._accent, 1.75)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen); p.setBrush(fill)
        p.drawPolygon(QPolygonF(pts))
        p.setPen(Qt.NoPen); p.setBrush(self._accent)
        for pt in pts:
            p.drawEllipse(pt, 1.9, 1.9)
        p.end()


class TrendChart(QWidget):
    """Eight trailing-week commit bars, the current week highlighted."""

    BAR_W, GAP, H = 20, 6, 60

    def __init__(self, accent: QColor, base: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._totals: list[int] = []
        self._accent = accent
        self._base = base
        self.setFixedHeight(self.H)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_data(self, totals: list[int]) -> None:
        self._totals = list(totals)
        w = len(self._totals) * self.BAR_W + max(0, len(self._totals) - 1) * self.GAP
        self.setFixedWidth(max(w, 1))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        if not self._totals:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hi = max(self._totals) or 1
        base = QColor(self._base); base.setAlpha(28)
        last = len(self._totals) - 1
        for i, v in enumerate(self._totals):
            h = max(3.0, (v / hi) * self.H)
            x = i * (self.BAR_W + self.GAP)
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, self.H - h, self.BAR_W, h), 3, 3)
            p.fillPath(path, self._accent if i == last else base)
        p.end()


class _ChurnBar(QWidget):
    """Thin two-segment insert/delete share bar."""

    def __init__(self, add: QColor, dele: QColor, track: QColor,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._share = 0.0     # insertions' share of churn
        self._empty = True
        self._add = add
        self._del = dele
        self._track = track
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_churn(self, insertions: int, deletions: int) -> None:
        churn = insertions + deletions
        self._empty = churn == 0
        self._share = (insertions / churn) if churn else 0.0
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, self.width(), 8), 4, 4)
        p.setClipPath(clip)
        if self._empty:
            p.fillRect(self.rect(), self._track)
        else:
            split = self.width() * self._share
            p.fillRect(QRectF(0, 0, split, 8), self._add)
            p.fillRect(QRectF(split, 0, self.width() - split, 8), self._del)
        p.end()


class EmptyState(QWidget):
    """Onboarding splash (no repos) / weekly-retro dashboard (repos).

    Construction is cheap and idempotent; safe to instantiate eagerly in
    `MainWindow.__init__` regardless of whether the user will ever see it.

    Attributes the tests rely on:
        ``_heading`` — the bold "ccwork" QLabel.
        ``_subhead`` — the version-and-tagline QLabel.
        ``_hints`` — list of hint QLabels; tests assert the count.
        ``_logo`` — the logo QLabel (may be hidden if loading failed).
        ``_pulse`` — the dashboard container (hidden until stats arrive).
        ``_narrative`` / ``_week_total`` / ``_trend_chart`` / ``_facts`` /
        ``_ship`` / ``_cards`` / ``_quiet_chips`` — the dashboard widgets.
        ``_tip`` — the rotating tip QLabel.
        ``_recovery`` — the crash-recovery banner (hidden until populated).
    """

    # Emitted when the user clicks Dismiss on the crash banner, and when a
    # copy button puts text on the clipboard. The widget owns no status bar;
    # MainWindow clears the recovery file / flashes a confirmation.
    recovery_dismissed = Signal()
    status_message = Signal(str)
    # (repo path, session id) — Launch was clicked; MainWindow opens a
    # terminal there running `claude --resume <id>`.
    resume_requested = Signal(str, str)

    LOGO_PX = 96

    def __init__(self, version: str, logo_path: Path | None = None,
                 parent: QWidget | None = None,
                 repos_provider: Callable[[], list[tuple[str, str]]] | None = None) -> None:
        super().__init__(parent)
        self._repos_provider = repos_provider
        self._worker: _StatsWorker | None = None
        self._tips = cycle(TIP_LINES)
        self._txt = self.palette().color(QPalette.WindowText)
        bg = self.palette().color(QPalette.Window)
        # Card fills are a translucent overlay over the window bg. White
        # lightens a dark theme; black darkens a light one — so the boxes
        # read either way. Pick the direction from the bg's lightness.
        self._overlay = "0,0,0" if bg.lightnessF() > 0.5 else "255,255,255"
        self._faint = _blend(_MUTED, bg, 0.45)

        # The dashboard can outgrow the window; scroll instead of clipping.
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;}")
        shell.addWidget(scroll)
        content = QWidget(self)
        content.setStyleSheet("background:transparent;")
        scroll.setWidget(content)

        # Centered single column. Outer HBox + stretches → horizontal centering;
        # the inner VBox + stretches → vertical centering. Either axis collapses
        # gracefully on a too-small window (top/bottom stretches absorb to zero,
        # word-wrap on the labels handles narrow widths).
        outer = QHBoxLayout(content)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addStretch(1)
        column = QVBoxLayout()
        outer.addLayout(column, 0)
        outer.addStretch(1)

        column.addStretch(1)

        # Crash-recovery banner: sits above everything so it's the first
        # thing read after an unclean shutdown. Hidden until `show_recovery`.
        self._recovery = self._build_recovery()
        self._recovery.hide()
        column.addWidget(self._recovery, 0, Qt.AlignHCenter)

        self._logo = QLabel(self)
        self._logo.setAlignment(Qt.AlignCenter)
        pixmap = self._render_logo(logo_path) if logo_path is not None else None
        self._logo_ok = pixmap is not None and not pixmap.isNull()
        if self._logo_ok:
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
        self._pulse = self._build_dashboard()
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

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(STATS_REFRESH_MS)
        self._stats_timer.timeout.connect(self.refresh_stats)

        column.addStretch(1)

    # ── shared label / card helpers ──

    def _label(self, text: str = "", *, color: QColor | None = None, pt: float = 10.0,
               bold: bool = False, upper: bool = False, spacing: float = 0.0,
               mono: bool = False, align=Qt.AlignLeft) -> QLabel:
        lbl = QLabel(text, self)
        f = QFont("monospace") if mono else QFont(self.font())
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
        f.setStyleSheet(f"QFrame{{background-color: rgba({self._overlay},{alpha});"
                        f" border-radius:{radius}px;}}")
        return f

    def _chip(self, text: str, *, color: QColor | None = None,
              bg: str | None = None, bold: bool = False) -> QLabel:
        lbl = self._label(text, color=color or self._faint, pt=8.0, mono=True, bold=bold)
        lbl.setStyleSheet(
            f"color:{(color or self._faint).name()};"
            f" background-color:{bg or f'rgba({self._overlay},0.055)'};"
            " border-radius:5px; padding:2px 8px;")
        return lbl

    # ── dashboard construction (skeleton; values land in `_apply_stats`) ──

    def _build_dashboard(self) -> QWidget:
        root = QWidget(self)
        root.setFixedWidth(DASH_W)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # 1. narrative header — the meaning reads first
        top = QHBoxLayout(); top.setSpacing(24)
        left = QVBoxLayout(); left.setSpacing(6)
        left.addWidget(self._label("This week", color=_MUTED, pt=11, bold=True,
                                   upper=True, spacing=1.4))
        self._narrative = self._label("", pt=13.0)
        self._narrative.setTextFormat(Qt.RichText)
        self._narrative.setWordWrap(True)
        left.addWidget(self._narrative)
        top.addLayout(left, 1)
        fresh = QVBoxLayout(); fresh.setSpacing(0)
        self._fresh_live = self._label("● live", color=_ACCENT_TREND, pt=8.6,
                                       mono=True, align=Qt.AlignRight)
        self._fresh_time = self._label("", color=self._faint, pt=8.6, mono=True,
                                       align=Qt.AlignRight)
        self._fresh_date = self._label("", color=self._faint, pt=8.6, mono=True,
                                       align=Qt.AlignRight)
        for w in (self._fresh_live, self._fresh_time, self._fresh_date):
            fresh.addWidget(w)
        fresh.addStretch(1)
        top.addLayout(fresh, 0)
        v.addLayout(top)
        v.addSpacing(18)

        # 2. trend hero — pattern, not a vanity number
        hero = self._card(14, 0.055)
        hv = QHBoxLayout(hero); hv.setContentsMargins(20, 18, 20, 18); hv.setSpacing(20)
        self._trend_chart = TrendChart(_ACCENT_TREND, self._txt, hero)
        hv.addWidget(self._trend_chart, 0, Qt.AlignBottom)
        read = QVBoxLayout(); read.setSpacing(5)
        read.addStretch(1)
        self._week_total = self._label("0", pt=22, bold=True)
        read.addWidget(self._week_total)
        self._week_caption = self._label("", color=_MUTED, pt=9)
        self._week_caption.setTextFormat(Qt.RichText)
        read.addWidget(self._week_caption)
        hv.addLayout(read)
        hv.addStretch(1)
        axis = QVBoxLayout()
        axis.addWidget(self._label("8 weeks", color=self._faint, pt=7.5, mono=True,
                                   align=Qt.AlignRight))
        axis.addStretch(1)
        axis.addWidget(self._label("now →", color=self._faint, pt=7.5, mono=True,
                                   align=Qt.AlignRight))
        hv.addLayout(axis)
        v.addWidget(hero)
        v.addSpacing(10)

        # 3. week-in-numbers (demoted, small)
        self._facts = self._label("", color=_MUTED, pt=9.4)
        self._facts.setTextFormat(Qt.RichText)
        v.addWidget(self._facts)
        v.addSpacing(16)

        # 4. celebration — the ONE bright moment (hidden without a release)
        self._ship = QFrame(self)
        self._ship.setStyleSheet(
            f"QFrame{{background-color: rgba(133,153,0,0.10);"
            f" border-left:3px solid {_ACCENT_GREEN.name()}; border-radius:12px;}}")
        sv = QHBoxLayout(self._ship)
        sv.setContentsMargins(16, 12, 16, 12); sv.setSpacing(12)
        sv.addWidget(self._label("◆ SHIPPED", color=_ACCENT_GREEN, pt=9, bold=True,
                                 mono=True, spacing=0.5))
        self._ship_what = self._label("", pt=10.5)
        self._ship_what.setTextFormat(Qt.RichText)
        sv.addWidget(self._ship_what)
        sv.addStretch(1)
        self._ship_when = self._label("", color=_MUTED, pt=8.6, mono=True)
        sv.addWidget(self._ship_when)
        self._ship.hide()
        v.addWidget(self._ship)
        v.addSpacing(22)

        # 5. per-repo bento
        active_hd = QHBoxLayout(); active_hd.setSpacing(10)
        active_hd.addWidget(self._label("Active this week", color=self._faint, pt=9,
                                        bold=True, upper=True, spacing=1.2))
        active_hd.addWidget(self._label(
            "— newest activity first · rolling 7 days, merges excluded",
            color=self._faint, pt=8.6))
        active_hd.addStretch(1)
        v.addLayout(active_hd)
        v.addSpacing(10)
        self._cards_grid = QGridLayout()
        self._cards_grid.setSpacing(14)
        self._cards: list[QFrame] = []
        v.addLayout(self._cards_grid)
        v.addSpacing(28)

        # 6. quiet strip
        self._quiet_hd = QHBoxLayout(); self._quiet_hd.setSpacing(10)
        self._quiet_title = self._label("Quiet", color=self._faint, pt=9, bold=True,
                                        upper=True, spacing=1.2)
        self._quiet_hd.addWidget(self._quiet_title)
        self._quiet_note = self._label("— no commits in 7 days · lifetime size",
                                       color=self._faint, pt=8.6)
        self._quiet_hd.addWidget(self._quiet_note)
        self._quiet_hd.addStretch(1)
        v.addLayout(self._quiet_hd)
        v.addSpacing(8)
        self._quiet_grid = QGridLayout()
        self._quiet_grid.setSpacing(8)
        self._quiet_chips: list[QLabel] = []
        v.addLayout(self._quiet_grid)
        return root

    def _tempo_label(self, rw: RepoWeek) -> QLabel:
        chip_bg = f"rgba({self._overlay},0.055)"
        if rw.release:
            text, fg, bg = f"◆ {rw.release}", QColor("#ffffff"), _ACCENT_GREEN.name()
        elif rw.new_from_zero:
            text, fg, bg = "▲ NEW", QColor("#ffffff"), _ACCENT_NEW.name()
        elif rw.delta < 0:
            text, fg, bg = f"▼ −{-rw.delta}", _MUTED, chip_bg
        elif rw.delta > 0:
            text, fg, bg = f"▲ +{rw.delta}", _MUTED, chip_bg
        else:
            text, fg, bg = "· steady", _MUTED, chip_bg
        lbl = self._label(text, color=fg, pt=8.6, bold=True, mono=True, spacing=0.4)
        lbl.setStyleSheet(f"color:{fg.name()}; background-color:{bg};"
                          " border-radius:8px; padding:4px 11px;")
        return lbl

    def _headline_caption(self, rw: RepoWeek, now: datetime) -> str:
        if rw.new_from_zero and rw.first_commit_ts:
            days = max(0, int((now.timestamp() - rw.first_commit_ts) // 86400))
            return f"commits · {days}d old"
        if rw.release:
            return "commits · a release"
        if rw.delta < 0:
            return f"commits · was {rw.prior_commits}"
        return "commits"

    def _repo_card(self, rw: RepoWeek, fp: tuple[float, ...], now: datetime) -> QFrame:
        card = self._card(14, 0.038)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(16, 15, 16, 13)
        cv.setSpacing(13)

        hd = QHBoxLayout(); hd.setSpacing(10)
        hd.addWidget(self._label(rw.name, pt=12.4, bold=True))
        hd.addStretch(1)
        hd.addWidget(self._tempo_label(rw))
        cv.addLayout(hd)

        body = QHBoxLayout(); body.setSpacing(14)
        radar = RadarChart(_ACCENT_NEW, self._txt, self._faint, card)
        radar.set_values(fp)
        body.addWidget(radar, 0, Qt.AlignVCenter)

        stats = QVBoxLayout(); stats.setSpacing(9)
        head = QHBoxLayout(); head.setSpacing(7)
        head.addWidget(self._label(str(rw.commits), pt=20, bold=True))
        head.addWidget(self._label(self._headline_caption(rw, now), color=_MUTED,
                                   pt=8.2, upper=True, spacing=1.0),
                       0, Qt.AlignBottom)
        head.addStretch(1)
        stats.addLayout(head)

        track_bg = QColor(self._txt); track_bg.setAlpha(13)
        bar = _ChurnBar(_ACCENT_GREEN, _DEL_COLOR, track_bg, card)
        bar.set_churn(rw.insertions, rw.deletions)
        stats.addWidget(bar)
        lg = QHBoxLayout(); lg.setSpacing(12)
        lg.addWidget(self._label(f"+{rw.insertions:,}", color=_ACCENT_GREEN,
                                 pt=8.6, bold=True, mono=True))
        lg.addWidget(self._label(f"−{rw.deletions:,}", color=_DEL_COLOR,
                                 pt=8.6, bold=True, mono=True))
        lg.addStretch(1)
        stats.addLayout(lg)

        ladder = QGridLayout(); ladder.setHorizontalSpacing(14); ladder.setVerticalSpacing(4)
        net = f"{'+' if rw.net >= 0 else '−'}{abs(rw.net):,}"
        net_color = _ACCENT_GREEN.name() if rw.net >= 0 else _DEL_COLOR.name()
        cells = (
            f'net <span style="color:{net_color}">{net}</span>',
            f'<span style="color:{self._txt.name()}"><b>{rw.new_files}</b></span> new files',
            f'<span style="color:{self._txt.name()}"><b>{rw.files_changed}</b></span> changed',
            f'<span style="color:{self._txt.name()}"><b>{rw.file_types}</b></span> file types',
            f'~<span style="color:{self._txt.name()}"><b>{rw.lines_per_commit}</b></span>'
            ' lines/commit',
            churn_tag(rw),
        )
        for i, cell in enumerate(cells):
            lbl = self._label("", color=_MUTED, pt=8.6, mono=True)
            lbl.setTextFormat(Qt.RichText)
            lbl.setText(cell)
            ladder.addWidget(lbl, i // 2, i % 2)
        stats.addLayout(ladder)
        body.addLayout(stats, 1)
        cv.addLayout(body)

        chips = QHBoxLayout(); chips.setSpacing(8)
        if rw.dirty:
            chips.addWidget(self._chip("uncommitted"))
        if rw.release:
            chips.addWidget(self._chip(f"shipped {rw.release}", color=_ACCENT_GREEN,
                                       bg="rgba(133,153,0,0.10)", bold=True))
        chips.addStretch(1)
        cv.addLayout(chips)
        return card

    # ── crash-recovery banner ──

    def _build_recovery(self) -> QFrame:
        """The crash banner skeleton. Rows land in `show_recovery`."""
        card = self._card(12, 0.12)
        card.setFixedWidth(440)
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(6)

        hdr = QHBoxLayout(); hdr.setSpacing(8)
        hdr.addWidget(self._label("⚠", color=_ACCENT_DIRTY, pt=14, bold=True))
        hdr.addWidget(self._label("ccwork didn't close cleanly",
                                  color=self._txt, pt=11, bold=True))
        hdr.addStretch(1)
        v.addLayout(hdr)

        v.addWidget(self._label("Claude sessions you can resume:",
                                color=_MUTED, pt=9))

        self._recovery_rows_lay = QVBoxLayout()
        self._recovery_rows_lay.setSpacing(2)
        self._recovery_row_widgets: list[QWidget] = []
        v.addLayout(self._recovery_rows_lay)

        foot = QHBoxLayout(); foot.addStretch(1)
        dismiss = QToolButton(card)
        dismiss.setText("Dismiss")
        dismiss.setAutoRaise(True)
        dismiss.setCursor(Qt.PointingHandCursor)
        dismiss.clicked.connect(lambda _=False: self._on_dismiss())
        foot.addWidget(dismiss)
        v.addLayout(foot)
        return card

    def show_recovery(self, entries: list[dict]) -> None:
        """Populate and reveal the banner. `entries` is a list of
        {"name", "id"} dicts (the "path" key is ignored here). An empty
        list hides the banner."""
        for w in self._recovery_row_widgets:
            self._recovery_rows_lay.removeWidget(w)
            w.deleteLater()
        self._recovery_row_widgets = []
        for e in entries:
            row = self._make_recovery_row(
                str(e.get("name", "")), str(e.get("id", "")), str(e.get("path", "")))
            self._recovery_rows_lay.addWidget(row)
            self._recovery_row_widgets.append(row)
        self._recovery.setVisible(bool(entries))

    def _make_recovery_row(self, name: str, session_id: str, path: str) -> QWidget:
        row = QWidget(self)
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(self._label(name or "(unknown repo)", color=self._txt, pt=10, bold=True))
        h.addStretch(1)

        short = session_id if len(session_id) <= 16 else session_id[:15] + "…"
        id_lbl = self._label(short, color=_MUTED, pt=9)
        mono = QFont("monospace"); mono.setPointSizeF(9.0)
        id_lbl.setFont(mono)
        id_lbl.setToolTip(session_id)
        h.addWidget(id_lbl)

        copy_btn = QPushButton("Copy", self)
        copy_btn.setToolTip("Copy this session's ID to the clipboard")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.clicked.connect(
            lambda _=False, s=session_id: self._copy(s, "Session ID copied")
        )
        h.addWidget(copy_btn)

        launch_btn = QPushButton("Launch", self)
        launch_btn.setToolTip("Open a terminal here running `claude --resume`")
        launch_btn.setCursor(Qt.PointingHandCursor)
        launch_btn.clicked.connect(
            lambda _=False, p=path, s=session_id: self.resume_requested.emit(p, s)
        )
        h.addWidget(launch_btn)
        return row

    def _copy(self, text: str, message: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self.status_message.emit(message)

    def _on_dismiss(self) -> None:
        self._recovery.hide()
        self.recovery_dismissed.emit()

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
        self._stats_timer.start()
        self.refresh_stats()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._tip_timer.stop()
        self._stats_timer.stop()

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

    def _set_onboarding(self, on: bool) -> None:
        """With repos the dashboard IS the page; the onboarding chrome
        (logo/heading/hints) only shows on an empty shelf."""
        self._logo.setVisible(on and self._logo_ok)
        self._heading.setVisible(on)
        self._subhead.setVisible(on)
        for h in self._hints:
            h.setVisible(on)

    def _apply_stats(self, stats: RepoStats) -> None:
        if stats.repo_count == 0:
            self._pulse.hide()
            self._set_onboarding(True)
            return
        self._set_onboarding(False)

        now = datetime.fromtimestamp(stats.gathered_ts) if stats.gathered_ts \
            else datetime.now()

        # 1. narrative + freshness
        self._narrative.setText(summarize(stats, now=now,
                                          release_color=_ACCENT_GREEN.name()))
        self._fresh_time.setText(now.strftime("as of %-I:%M %p").lower())
        self._fresh_date.setText(now.strftime("%-d %b %Y"))

        # 2. trend hero
        self._trend_chart.set_data(stats.weekly_totals)
        total = stats.week_total
        self._week_total.setText(str(total))
        avg = stats.four_week_avg
        if avg > 0:
            if total > avg:
                cmp_txt = (f'<span style="color:{_ACCENT_GREEN.name()}">▲ over your'
                           f' 4-wk avg of {avg:.0f}</span>')
            elif total < avg:
                cmp_txt = (f'<span style="color:{self._faint.name()}">▼ under your'
                           f' 4-wk avg of {avg:.0f}</span>')
            else:
                cmp_txt = f'<span style="color:{self._faint.name()}">≈ level with' \
                          ' your 4-wk avg</span>'
            self._week_caption.setText(f"commits this week · {cmp_txt}")
        else:
            self._week_caption.setText("commits this week")

        # 3. facts
        ink = self._txt.name()
        n_rel = len(stats.releases)
        facts = [
            f'<span style="color:{_ACCENT_GREEN.name()}">+{_knum(stats.total_insertions)}'
            f'</span> / <span style="color:{_DEL_COLOR.name()}">'
            f'−{_knum(stats.total_deletions)}</span> lines',
            f'<span style="color:{ink}"><b>{stats.total_new_files}</b></span> new files',
            f'<span style="color:{ink}"><b>{len(stats.active)}</b></span>'
            f' of {stats.repo_count} repos active',
        ]
        if n_rel:
            facts.append(f'<span style="color:{ink}"><b>{n_rel}</b></span>'
                         f' release{"s" if n_rel > 1 else ""}')
        self._facts.setText("&nbsp;&nbsp;·&nbsp;&nbsp;".join(facts))

        # 4. celebration
        releases = stats.releases
        if releases:
            r = max(releases, key=lambda r: r.release_ts or 0)
            self._ship_what.setText(
                f'<b>{r.name}</b> <span style="font-family:monospace">{r.release}</span>')
            self._ship_when.setText(relative_time(r.release_ts, now)
                                    if r.release_ts else "")
            self._ship.show()
        else:
            self._ship.hide()

        # 5. bento cards (rebuilt each sweep)
        for card in self._cards:
            self._cards_grid.removeWidget(card)
            card.deleteLater()
        self._cards = []
        fps = fingerprints(stats.active)
        for i, rw in enumerate(stats.active):
            card = self._repo_card(rw, fps.get(rw.path, (0.0,) * len(RADAR_AXES)), now)
            self._cards_grid.addWidget(card, i // 2, i % 2)
            self._cards.append(card)

        # 6. quiet strip (hidden entirely when every repo is active)
        for chip in self._quiet_chips:
            self._quiet_grid.removeWidget(chip)
            chip.deleteLater()
        self._quiet_chips = []
        for i, rw in enumerate(stats.quiet):
            state = ('<span style="color:%s">uncommitted</span>' % _DEL_COLOR.name()
                     if rw.dirty else "idle")
            chip = self._label("", color=_MUTED, pt=8.6, mono=True)
            chip.setTextFormat(Qt.RichText)
            chip.setText(f'<span style="color:{ink}"><b>{rw.name}</b></span>'
                         f' {rw.lifetime_commits} · {state}')
            chip.setStyleSheet(f"color:{_MUTED.name()};"
                               f" background-color: rgba({self._overlay},0.038);"
                               " border-radius:8px; padding:6px 11px;")
            self._quiet_grid.addWidget(chip, i // 3, i % 3)
            self._quiet_chips.append(chip)
        show_quiet = bool(stats.quiet)
        self._quiet_title.setVisible(show_quiet)
        self._quiet_note.setVisible(show_quiet)

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
        # gather_stats is documented exception-free on bad repos, so no
        # blanket catch here — a real bug should surface, not be swallowed.
        self.done.emit(gather_stats(self._repos))
