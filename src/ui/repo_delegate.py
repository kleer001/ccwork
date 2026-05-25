"""Item delegate that paints each repo row: name + branch + right-edge badge.

Two-line rows with a reserved right-edge column for the Claude-alert badge
(working spinner / done / attention / background-agent twinkle / ambient
terminal state) and a left-edge stripe for the last-focused bookmark.
Geometry knobs come from `settings.ui.layout`; glyphs and colors come from
`badge_theme`. Row roles are defined in `repo_model`.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from src.core.repo_store import Repo
from src.ui import badge_theme
from src.ui.badge_theme import (
    BG_AGENT_FRAMES,
    SESSION_ACTIVE_GLYPH,
    STATUS_ATTENTION,
    TERMINAL_ONLY_GLYPH,
    spinner_for_id,
)
from src.ui.repo_model import (
    ROLE_BG_AGENTS,
    ROLE_BRANCH,
    ROLE_HAS_TERMINAL,
    ROLE_LAST_FOCUSED,
    ROLE_PATH_MISSING,
    ROLE_REPO,
    ROLE_SESSION_ACTIVE,
    ROLE_STATUS,
    ROLE_WORKING,
)


# Paint width (px) of the right-edge column for the animated glyphs — the
# spinner, the bg-agent twinkle, and the ambient terminal-state mark. Distinct
# from the LayoutSettings `glyph_w` (the reserved dot / static-glyph column).
BADGE_COL_W = 16


class RepoDelegate(QStyledItemDelegate):
    """Two-line row: name (bold) + branch (subtitle), unread badge right-aligned.

    All numeric layout knobs (row_height, padding_x, group_gap_h, glyph_w,
    glyph_gap, active_stripe_w, last_focused_stripe_w) come from
    `settings.ui.layout` — assigned as instance attributes by __init__ so
    they're read consistently as `self.ROW_HEIGHT` etc. The legacy uppercase
    names are kept to minimize delta in the paint code.
    """

    # Badge palette lives in badge_theme (the single theming source).
    # Re-exposed as class attributes so the paint code reads them as
    # self.STATUS_COLORS etc. and tests can read them off the class.
    STATUS_COLORS = badge_theme.STATUS_COLORS
    STATUS_GLYPHS = badge_theme.STATUS_GLYPHS
    SPINNER_COLOR = badge_theme.SPINNER_COLOR
    BG_AGENTS_COLOR = badge_theme.BG_AGENTS_COLOR
    AMBIENT_COLOR = badge_theme.AMBIENT_COLOR
    LAST_FOCUSED_BASE = badge_theme.LAST_FOCUSED_BASE

    def __init__(self, parent=None, layout=None) -> None:
        super().__init__(parent)
        # Advanced by RepoSidebar's QTimer; read every paint.
        self.spinner_frame = 0
        # "dot" or "glyph". Toggled live by RepoSidebar.set_badge_style.
        self.badge_style = "dot"
        # Mirrors ui.group_active_repos. RepoSidebar keeps it in sync.
        self.group_enabled = False
        # Layout knobs from settings; defaults match the historical hardcodes
        # so tests that construct a delegate without settings still behave.
        from src.core.settings import LayoutSettings
        L = layout or LayoutSettings()
        self.ROW_HEIGHT = L.row_height
        self.PADDING_X = L.padding_x
        self.GROUP_GAP_H = L.group_gap_h
        self.GLYPH_W = L.glyph_w
        self.GLYPH_GAP = L.glyph_gap
        self.ACTIVE_STRIPE_W = L.active_stripe_w
        self.LAST_FOCUSED_STRIPE_W = L.last_focused_stripe_w

    def _is_group_boundary(self, index: QModelIndex) -> bool:
        """Is `index` the first inactive row directly below an active one?"""
        if not self.group_enabled or not index.isValid() or index.row() == 0:
            return False
        if bool(index.data(ROLE_HAS_TERMINAL)):
            return False
        prev = index.model().index(index.row() - 1)
        return bool(prev.data(ROLE_HAS_TERMINAL))

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        h = self.ROW_HEIGHT
        if self._is_group_boundary(index):
            h += self.GROUP_GAP_H
        return QSize(option.rect.width(), h)

    @classmethod
    def _last_focused_stripe_color(cls, palette) -> QColor:
        """Theme-aware violet for the bookmark stripe.

        The stripe is meant to be a quiet "you were here" cue, not an alert.
        We push the base hue *toward* the row background — lighter on light
        themes, darker on dark themes — so the eye doesn't read it as a
        Claude-driven status change.
        """
        base = palette.base().color()
        if base.lightness() < 128:
            return cls.LAST_FOCUSED_BASE.darker(160)
        return cls.LAST_FOCUSED_BASE.lighter(140)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()

        # Group boundary: paint a strip of widget bg above the row so the
        # active-vs-inactive groups read as separate clusters. The remaining
        # area becomes the row proper — stash it back on `option.rect` so
        # all the existing geometry math below stays one-line-of-code simple.
        if self._is_group_boundary(index):
            gap_rect = QRect(
                option.rect.left(), option.rect.top(),
                option.rect.width(), self.GROUP_GAP_H,
            )
            painter.fillRect(gap_rect, option.palette.window())
            option.rect = option.rect.adjusted(0, self.GROUP_GAP_H, 0, 0)

        # Background: honor selection state. The selected row IS the active
        # repo because selecting switches the stack. Paint the Active palette
        # unconditionally so xterm stealing focus doesn't dim the highlight.
        selected = bool(option.state & option.state.State_Selected)
        if selected:
            painter.fillRect(option.rect, option.palette.highlight())
            text_color = option.palette.highlightedText().color()
            # Thin accent stripe on the left edge for extra glance-ability.
            # Uses highlightedText for contrast against the highlight bg.
            stripe_rect = QRect(
                option.rect.left(), option.rect.top(),
                self.ACTIVE_STRIPE_W, option.rect.height(),
            )
            painter.fillRect(stripe_rect, option.palette.highlightedText())
        else:
            painter.fillRect(option.rect, option.palette.base())
            text_color = option.palette.text().color()

        # Thin border around the row so each repo reads as a discrete button
        # rather than a continuous list. palette.mid() is the Qt-blessed
        # subtle-separator color — auto-adjusts for light/dark themes.
        # Drawn one pixel inside option.rect so adjacent rows share an edge
        # without a visible double-line.
        border_pen = QPen(option.palette.mid().color(), 1)
        painter.setPen(border_pen)
        painter.setBrush(Qt.NoBrush)
        # QRect's right/bottom are inclusive — subtract 1 so the stroke fits.
        border_rect = option.rect.adjusted(0, 0, -1, -1)
        painter.drawRect(border_rect)

        repo: Repo = index.data(ROLE_REPO)
        branch: str | None = index.data(ROLE_BRANCH)
        status: str = index.data(ROLE_STATUS) or ""
        working: bool = bool(index.data(ROLE_WORKING))
        has_terminal: bool = bool(index.data(ROLE_HAS_TERMINAL))
        last_focused: bool = bool(index.data(ROLE_LAST_FOCUSED))
        path_missing: bool = bool(index.data(ROLE_PATH_MISSING))
        bg_agents: int = int(index.data(ROLE_BG_AGENTS) or 0)
        session_active: bool = bool(index.data(ROLE_SESSION_ACTIVE))
        # Ambient badges fire iff the row has a terminal. Without a
        # terminal there's nothing to be "in" or "exited from".
        ambient_glyph = ""
        if has_terminal:
            ambient_glyph = SESSION_ACTIVE_GLYPH if session_active else TERMINAL_ONLY_GLYPH

        # Last-focused bookmark: thin left-edge stripe instead of a right-edge
        # dot, so the badge column stays reserved for genuine Claude alerts.
        # Skip when the row is selected — the active stripe owns that edge.
        if not selected and last_focused:
            lf_rect = QRect(
                option.rect.left(), option.rect.top(),
                self.LAST_FOCUSED_STRIPE_W, option.rect.height(),
            )
            painter.fillRect(lf_rect, self._last_focused_stripe_color(option.palette))

        # Row-number hint in the top-left gutter — discoverability for the
        # Ctrl+Shift+N jump bindings (only mapped for slots 1..9). Lives in
        # the PADDING_X gutter between the left-edge stripes and the text,
        # so the existing layout math is undisturbed. Alpha-reduced and at
        # 0.75x the row font so it reads as an ambient label rather than a
        # competing visual.
        row_num = index.row() + 1
        if row_num <= 9:
            num_color = QColor(text_color)
            num_color.setAlpha(140)
            num_font = QFont(option.font)
            num_font.setPointSizeF(option.font.pointSizeF() * 0.75)
            painter.setFont(num_font)
            painter.setPen(QPen(num_color))
            stripe_w = max(self.ACTIVE_STRIPE_W, self.LAST_FOCUSED_STRIPE_W)
            num_rect = QRect(
                option.rect.left() + stripe_w + 1,
                option.rect.top() + 2,
                self.PADDING_X - stripe_w - 1,
                12,
            )
            painter.drawText(num_rect, Qt.AlignLeft | Qt.AlignTop, str(row_num))

        rect = option.rect.adjusted(self.PADDING_X, 4, -self.PADDING_X, -4)

        # Reserve the right-edge glyph column whenever the row has a status
        # to show. Text elides to fit; the badge stays put.
        # Untouched-this-session rows render italic + regular weight so the
        # eye can pick out which repos already have a live terminal without
        # using color (which would compete with the status badge).
        name_font = QFont(option.font)
        name_font.setBold(has_terminal)
        name_font.setItalic(not has_terminal)
        show_glyph = (
            working
            or (status in self.STATUS_COLORS)
            or bg_agents > 0
            or bool(ambient_glyph)
        )
        glyph_room = self.GLYPH_W + self.GLYPH_GAP
        text_w = max(0, rect.width() - (glyph_room if show_glyph else 0))

        # Repo name (bold) on line 1. Elide at the right so we don't bleed
        # under the glyph column.
        painter.setFont(name_font)
        painter.setPen(QPen(text_color))
        name_rect = QRect(rect.left(), rect.top(), text_w, rect.height() // 2)
        name_text = painter.fontMetrics().elidedText(
            repo.display_name if repo else "", Qt.ElideRight, text_w,
        )
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, name_text)

        # Branch subtitle on line 2.
        sub_font = QFont(option.font)
        sub_font.setPointSizeF(option.font.pointSizeF() * 0.9)
        painter.setFont(sub_font)
        painter.setPen(QPen(text_color.lighter(130) if text_color.lightness() < 128 else text_color.darker(140)))
        # Three-way pick: a missing path masks the detached/branch question
        # because git can't tell us anything about a dir that isn't there.
        # current_branch() returns None for both detached HEAD and missing
        # path, so we lean on the separate path_missing axis to disambiguate.
        if not repo:
            sub_text_raw = ""
        elif path_missing:
            sub_text_raw = "(path missing)"
        elif branch:
            sub_text_raw = branch
        else:
            sub_text_raw = "(detached)"
        sub_rect = QRect(rect.left(), rect.top() + rect.height() // 2, text_w, rect.height() // 2)
        sub_text = painter.fontMetrics().elidedText(sub_text_raw, Qt.ElideRight, text_w)
        painter.drawText(sub_rect, Qt.AlignLeft | Qt.AlignVCenter, sub_text)

        if not show_glyph:
            painter.restore()
            return

        # Right-edge glyph priority (highest first):
        #   attention dot (so a permission_prompt is glanceable even with
        #     desktop notifications off)
        #   working spinner (main turn active)
        #   color-coded status dot (DONE — never coincides with working
        #     since Stop clears working before setting done)
        #   background-agent twinkle (main turn idle but detached subagents
        #     still running — cycles ·→✦→✶→❋→✶→✦ in solarized cyan so the
        #     eye reads it as live secondary work, not a main-turn spinner)
        if working and status != STATUS_ATTENTION:
            spin_font = QFont(option.font)
            spin_font.setPointSizeF(option.font.pointSizeF() * 1.4)
            spin_font.setBold(True)
            painter.setFont(spin_font)
            painter.setPen(QPen(self.SPINNER_COLOR))
            frames = spinner_for_id(repo.id)
            frame = frames[self.spinner_frame % len(frames)]
            spin_rect = QRect(rect.right() - BADGE_COL_W, rect.top(), BADGE_COL_W, rect.height())
            painter.drawText(spin_rect, Qt.AlignRight | Qt.AlignVCenter, frame)
        else:
            color = self.STATUS_COLORS.get(status)
            if color is None and bg_agents > 0:
                bg_font = QFont(option.font)
                bg_font.setPointSizeF(option.font.pointSizeF() * 1.4)
                bg_font.setBold(True)
                painter.setFont(bg_font)
                painter.setPen(QPen(self.BG_AGENTS_COLOR))
                frame = BG_AGENT_FRAMES[self.spinner_frame % len(BG_AGENT_FRAMES)]
                bg_rect = QRect(rect.right() - BADGE_COL_W, rect.top(), BADGE_COL_W, rect.height())
                painter.drawText(bg_rect, Qt.AlignRight | Qt.AlignVCenter, frame)
            elif color is not None:
                if self.badge_style == "glyph":
                    glyph = self.STATUS_GLYPHS.get(status, "")
                    g_font = QFont(option.font)
                    g_font.setPointSizeF(option.font.pointSizeF() * 1.4)
                    g_font.setBold(True)
                    painter.setFont(g_font)
                    painter.setPen(QPen(color))
                    g_rect = QRect(rect.right() - self.GLYPH_W, rect.top(),
                                   self.GLYPH_W, rect.height())
                    painter.drawText(g_rect, Qt.AlignRight | Qt.AlignVCenter, glyph)
                else:
                    dot_d = 10
                    dot_rect = QRect(
                        rect.right() - dot_d,
                        rect.top() + (rect.height() - dot_d) // 2,
                        dot_d,
                        dot_d,
                    )
                    # 1px contrast stroke in the row's text color — Qt palette
                    # already guarantees that color contrasts with the row bg
                    # (selected or not), so the dot stays legible on turquoise
                    # highlights, dark themes, light themes, etc. without any
                    # color guessing on our part.
                    stroke = QPen(text_color, 1)
                    painter.setPen(stroke)
                    painter.setBrush(color)
                    painter.setRenderHint(QPainter.Antialiasing, True)
                    painter.drawEllipse(dot_rect)
            elif ambient_glyph:
                # Lowest-priority tier: ambient terminal-state. Paints only
                # when no working spinner, no DONE/ATTENTION dot, and no
                # background-agent twinkle owns the column.
                a_font = QFont(option.font)
                a_font.setPointSizeF(option.font.pointSizeF() * 1.4)
                painter.setFont(a_font)
                painter.setPen(QPen(self.AMBIENT_COLOR))
                a_rect = QRect(rect.right() - BADGE_COL_W, rect.top(), BADGE_COL_W, rect.height())
                painter.drawText(a_rect, Qt.AlignRight | Qt.AlignVCenter, ambient_glyph)

        painter.restore()
