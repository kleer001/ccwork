"""Item delegate that paints each repo row: name + branch + edge badges.

Three text lines (title, "repo · branch", status text) in the order, sizes
and type of `settings.ui.rows`, with two reserved right-edge badge slots:
  • OUTBOARD (rightmost): main-turn indicators — alert dots / compaction
    glyph / working spinner / DONE dot / ambient terminal state.
  • INBOARD (one slot to its left, only when subagents > 0): the
    SUBAGENT_FRAMES twinkle, painted alongside whatever's outboard so
    parallel work is glanceable while the main turn is also live.
A separate left-edge stripe hosts the last-focused bookmark in a different
paint pass. Geometry knobs come from `settings.ui.layout`; glyphs and
colors come from `badge_theme`. Row roles are defined in `repo_model`.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from src.core.repo_store import Repo
from src.core.settings import LayoutSettings, RowLineSettings, RowSettings
from src.ui import badge_theme
from src.ui.badge_theme import (
    PRIORITY_GLYPH,
    PRIORITY_TEXT,
    SESSION_ACTIVE_GLYPH,
    STATUS_DONE,
    SUBAGENT_FRAMES,
    WORKTREE_COLOR,
    WORKTREE_GLYPH,
    current_accent,
    spinner_for_id,
)
from src.ui.current_highlight import Highlight, paint_row, row_band
from src.ui.qt_theme import blend
from src.ui.repo_model import (
    ROLE_ACTIVE_GROUP,
    ROLE_BRANCH,
    ROLE_COMPACTING,
    ROLE_HAS_TERMINAL,
    ROLE_LAST_FOCUSED,
    ROLE_PATH_MISSING,
    ROLE_PRIORITY,
    ROLE_REPO,
    ROLE_SESSION_ACTIVE,
    ROLE_STATUS,
    ROLE_STATUS_TEXT,
    ROLE_SUBAGENTS,
    ROLE_TITLE,
    ROLE_WORKING,
    ROLE_WORKTREE_OF,
)


# Paint width (px) of each animated badge column. The main-turn indicator
# sits in the outboard (rightmost) slot; the subagent twinkle sits one slot
# inboard. Distinct from the LayoutSettings `glyph_w` (the reserved dot /
# static-glyph column).
BADGE_COL_W = 16

# The subagent twinkle advances one frame every Nth spinner tick, so it reads
# as a slow gentle bloom next to the faster braille spinner rather than a
# second frenetic animation competing for attention.
SUBAGENT_SLOWDOWN = 3

# Animated badge glyphs (spinner, twinkle, status glyph, ambient mark) paint
# enlarged relative to the row font so they read as marks, not body text.
GLYPH_FONT_SCALE = 1.4

# Separator between the repo name, the branch and the title, on line 2 and
# in the title tab. A worktree row puts the worktree glyph in place of the
# dot between its main checkout's name and the branch.
REPO_LINE_SEP = "  ·  "
WORKTREE_LINE_SEP = f"  {WORKTREE_GLYPH}  "


# Natural line height per px of font size. The "sized" and "packed" layouts
# share the row's text height in proportion to it, as mockups/panel-text.html
# does.
LINE_HEIGHT = 1.15

# The "marker" highlight color for a row text line.
MARKER_COLOR = QColor("#fff1a8")


def line_slots(rows: RowSettings, line_ids: list[str]) -> tuple[float, list[tuple[str, float, float]]]:
    """Share the row's text height between `line_ids`, per `rows.layout`.
    Returns the text scale (at most 1, so the text fits the height) and
    each line's (id, top, height), with top measured from the text top."""
    avail = rows.height - 2 * rows.inset
    natural = [getattr(rows, i).size * LINE_HEIGHT for i in line_ids]
    total = sum(natural)
    if rows.layout == "equal":
        slot = avail / len(line_ids)
        return min(1.0, slot / max(natural)), [(i, n * slot, slot) for n, i in enumerate(line_ids)]
    slots = []
    if rows.layout == "sized":
        y = 0.0
        for i, h in zip(line_ids, natural):
            slots.append((i, y, avail * h / total))
            y += avail * h / total
        return min(1.0, avail / total), slots
    gaps = rows.gap * (len(line_ids) - 1)
    scale = min(1.0, max(0.0, avail - gaps) / total)
    y = (avail - (total * scale + gaps)) / 2
    for i, h in zip(line_ids, natural):
        slots.append((i, y, h * scale))
        y += h * scale + rows.gap
    return scale, slots


def fit_line(fm, head: str, tail: str, width: int, sep: str = REPO_LINE_SEP) -> str:
    """Fit "head · tail" (`sep` between) into `width` px. The tail elides
    first; once no tail character fits, the head alone elides."""
    full = f"{head}{sep}{tail}" if tail else head
    if fm.horizontalAdvance(full) <= width or not tail:
        return fm.elidedText(full, Qt.ElideRight, width)
    lead = f"{head}{sep}"
    room = width - fm.horizontalAdvance(lead)
    rest = fm.elidedText(tail, Qt.ElideRight, room) if room > 0 else ""
    if rest and rest != "…":
        return lead + rest
    return fm.elidedText(head, Qt.ElideRight, width)


class RepoDelegate(QStyledItemDelegate):
    """Three-line row: title (bold), "repo · branch", status text; badges right-aligned.

    All numeric layout knobs (padding_x, group_gap_h, glyph_w, glyph_gap,
    active_stripe_w, last_focused_stripe_w) come from `settings.ui.layout`
    — assigned as instance attributes by __init__ so they're read
    consistently as `self.PADDING_X` etc. The legacy uppercase names are
    kept to minimize delta in the paint code. The row height and text come
    from `settings.ui.rows`, kept as `self.rows`.
    """

    # Badge palette lives in badge_theme (the single theming source).
    # Re-exposed as class attributes so the paint code reads them as
    # self.STATUS_COLORS etc. and tests can read them off the class.
    STATUS_COLORS = badge_theme.STATUS_COLORS
    STATUS_GLYPHS = badge_theme.STATUS_GLYPHS
    SPINNER_COLOR = badge_theme.SPINNER_COLOR
    SUBAGENT_COLOR = badge_theme.SUBAGENT_COLOR
    AMBIENT_COLOR = badge_theme.AMBIENT_COLOR
    COMPACT_COLOR = badge_theme.COMPACT_COLOR
    COMPACT_GLYPH = badge_theme.COMPACT_GLYPH
    LAST_FOCUSED_BASE = badge_theme.LAST_FOCUSED_BASE

    def __init__(self, parent=None, layout=None, rows: RowSettings | None = None) -> None:
        super().__init__(parent)
        # Advanced by RepoSidebar's QTimer; read every paint.
        self.spinner_frame = 0
        # "dot" or "glyph". Toggled live by RepoSidebar.set_badge_style.
        self.badge_style = "dot"
        # Mirrors ui.show_status_text. RepoSidebar keeps it in sync.
        self.show_status_text = True
        # Mirrors ui.group_active_repos. RepoSidebar keeps it in sync.
        self.group_enabled = False
        # The current-row highlight, or None. Set by RepoSidebar.set_highlight.
        self.highlight: Highlight | None = None
        # Repo ids whose priority flash is in its "on" phase. Set by
        # RepoSidebar's flash timer.
        self.flash_ids: set[str] = set()
        # Repo ids whose status badge pops in, mapped to the badge's scale.
        # Set by RepoSidebar's pop animations.
        self.pop_scale: dict[str, float] = {}
        # Layout knobs from settings; defaults match the historical hardcodes
        # so tests that construct a delegate without settings still behave.
        L = layout or LayoutSettings()
        self.rows = rows or RowSettings()
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
        if bool(index.data(ROLE_ACTIVE_GROUP)):
            return False
        prev = index.model().index(index.row() - 1)
        return bool(prev.data(ROLE_ACTIVE_GROUP))

    def row_rect(self, index: QModelIndex, rect: QRect) -> QRect:
        """The painted row inside its item `rect`: below the group gap."""
        if self._is_group_boundary(index):
            return rect.adjusted(0, self.GROUP_GAP_H, 0, 0)
        return rect

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        # The text shrinks to fit the row height (line_slots).
        h = self.rows.height
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

    @staticmethod
    def _line_color(line: RowLineSettings, text: QColor, base: QColor, row: int) -> QColor:
        if line.color == "text":
            color = QColor(text)
        elif line.color == "sub":
            color = text.lighter(130) if text.lightness() < 128 else text.darker(140)
        elif line.color == "muted":
            color = blend(text, base, 0.35)
        elif line.color == "accent":
            color = QColor(current_accent(row))
        else:
            color = QColor(line.color)
        color.setAlphaF(color.alphaF() * line.opacity / 100)
        return color

    @staticmethod
    def _highlight_color(line: RowLineSettings, base: QColor, row: int) -> QColor:
        if line.highlight_color == "accent":
            return blend(base, current_accent(row), 0.25)
        if line.highlight_color == "marker":
            return QColor(MARKER_COLOR)
        return QColor(line.highlight_color)

    @staticmethod
    def _line_font(base: QFont, line: RowLineSettings, scale: float, bold: bool, italic: bool) -> QFont:
        font = QFont(base)
        if line.family:
            font.setFamily(line.family)
        font.setPixelSize(max(1, round(line.size * scale)))
        font.setBold(bold)
        font.setItalic(italic)
        font.setUnderline(line.underline)
        font.setStrikeOut(line.strike)
        font.setLetterSpacing(QFont.AbsoluteSpacing, line.tracking)
        if line.caps:
            font.setCapitalization(QFont.AllUppercase)
        elif line.small_caps:
            font.setCapitalization(QFont.SmallCaps)
        return font

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
            option.rect = self.row_rect(index, option.rect)

        # Background: honor selection state. The selected row IS the active
        # repo because selecting switches the stack. Paint the Active palette
        # unconditionally so xterm stealing focus doesn't dim the highlight.
        selected = bool(option.state & option.state.State_Selected)
        h = self.highlight
        band = row_band(option.widget.viewport(), option.rect, h) if h and h.band else None
        # The band slides from row to row, so every row it touches paints
        # its part. Without a band, the selected row paints the shape.
        current = h is not None and (band.intersects(option.rect) if band else selected)
        if current:
            # The row's segment of the current-row highlight shape; the
            # side that faces the terminal stays open for the bridge.
            painter.fillRect(option.rect, option.palette.base())
            painter.save()
            painter.setClipRect(option.rect, Qt.IntersectClip)
            paint_row(painter, band or option.rect, h)
            painter.restore()
            text_color = option.palette.text().color()
        elif selected and h is None:
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
        repo: Repo = index.data(ROLE_REPO)
        if repo and repo.id in self.flash_ids:
            painter.fillRect(option.rect, current_accent(index.row()))

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
        if not current:  # the accent edges replace it on the current row
            painter.drawRect(border_rect)

        branch: str | None = index.data(ROLE_BRANCH)
        status: str = index.data(ROLE_STATUS) or ""
        working: bool = bool(index.data(ROLE_WORKING))
        has_terminal: bool = bool(index.data(ROLE_HAS_TERMINAL))
        last_focused: bool = bool(index.data(ROLE_LAST_FOCUSED))
        path_missing: bool = bool(index.data(ROLE_PATH_MISSING))
        subagents: int = int(index.data(ROLE_SUBAGENTS) or 0)
        session_active: bool = bool(index.data(ROLE_SESSION_ACTIVE))
        compacting: bool = bool(index.data(ROLE_COMPACTING))
        title_text: str = index.data(ROLE_TITLE) or ""
        status_text: str = index.data(ROLE_STATUS_TEXT) or ""
        # The ambient badge marks a live Claude session, nothing else. A
        # terminal left at a bare bash prompt gets no glyph at all — it's
        # not pending work, and a badge there reads as an unfinished task.
        ambient_glyph = SESSION_ACTIVE_GLYPH if (has_terminal and session_active) else ""

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

        rows = self.rows
        rect = option.rect.adjusted(self.PADDING_X, rows.inset, -self.PADDING_X, -rows.inset)

        # Reserve the right-edge glyph column whenever the row has a status
        # to show. Text elides to fit; the badge stays put.
        show_right_glyph = (
            working
            or compacting
            or (status in self.STATUS_COLORS)
            or bool(ambient_glyph)
        )
        show_subagent = subagents > 0
        # Both badges live on the right edge: the main-turn glyph in the
        # outboard (rightmost) slot, the subagent twinkle one slot inboard.
        # Text reserves one column per occupied slot and elides to fit.
        glyph_room = self.GLYPH_W + self.GLYPH_GAP
        right_cols = (1 if show_right_glyph else 0) + (1 if show_subagent else 0)
        text_w = max(0, rect.width() - right_cols * glyph_room)

        # Line text. The title is the flag, the emoji and the editable title.
        # The repo line is "name (II) · branch", with a three-way pick for
        # the branch part: a missing path masks the detached/branch question
        # because git can't tell us anything about a dir that isn't there.
        # current_branch() returns None for both detached HEAD and missing
        # path, so we lean on the separate path_missing axis to disambiguate.
        # Priority reads as words on the status line, in the row's accent;
        # with no status line to carry them, the glyph leads line 1 instead.
        priority = bool(index.data(ROLE_PRIORITY))
        status_shown = self.show_status_text and rows.status.visible
        flag = PRIORITY_GLYPH if priority and not status_shown else ""
        priority_mark = f"{PRIORITY_GLYPH} {PRIORITY_TEXT}" if priority and status_shown else ""
        texts = {
            "title": " ".join(p for p in ((flag, repo.emoji, title_text) if repo else ()) if p),
            "status": status_text if self.show_status_text else "",
        }
        worktree_of: str = index.data(ROLE_WORKTREE_OF) or ""
        sep = WORKTREE_LINE_SEP if worktree_of else REPO_LINE_SEP
        if not repo:
            name, branch_text = "", ""
        else:
            name = f"{worktree_of}{repo.instance_suffix}" if worktree_of else repo.instance_name
            if path_missing:
                branch_text = "(path missing)"
            elif branch:
                branch_text = branch
            else:
                branch_text = "(detached)"

        line_ids = [i for i in rows.order if getattr(rows, i).visible or not rows.collapse_hidden]
        scale, slots = line_slots(rows, line_ids)
        base = option.palette.base().color()
        for line_id, top, height in slots:
            line: RowLineSettings = getattr(rows, line_id)
            if not line.visible:
                continue
            # A title that follows the terminal paints bold when the row has
            # one and italic when not, so the eye can pick out the live
            # repos without a color that competes with the status badge.
            if line_id == "title" and line.follow_terminal:
                bold, italic = has_terminal, not has_terminal
            else:
                bold, italic = line.bold, line.italic
            painter.setFont(self._line_font(option.font, line, scale, bold, italic))
            fm = painter.fontMetrics()
            pri = priority_mark if line_id == "status" else ""
            if pri and texts[line_id]:
                pri = f" · {pri}"
            pri_w = fm.horizontalAdvance(pri)
            if line_id == "repo":
                text = fit_line(fm, name, branch_text, text_w, sep)
            else:
                text = fm.elidedText(texts[line_id], Qt.ElideRight, max(0, text_w - pri_w))
            slot = QRectF(rect.left(), rect.top() + top, text_w, height)
            if line.highlight and text:
                mark_h = fm.height()
                painter.fillRect(
                    QRectF(slot.left() - 2, slot.center().y() - mark_h / 2,
                           fm.horizontalAdvance(text) + 4, mark_h),
                    self._highlight_color(line, base, index.row()),
                )
            line_color = self._line_color(line, text_color, base, index.row())
            painter.setPen(QPen(line_color))
            if line_id == "repo" and worktree_of and WORKTREE_COLOR and text.startswith(name + sep):
                # Three runs, so only the glyph takes the worktree color.
                lead = name + sep[:sep.index(WORKTREE_GLYPH)]
                rest = text[len(lead) + len(WORKTREE_GLYPH):]
                painter.drawText(slot, Qt.AlignLeft | Qt.AlignVCenter, lead)
                x = fm.horizontalAdvance(lead)
                painter.setPen(QPen(WORKTREE_COLOR))
                painter.drawText(slot.adjusted(x, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter,
                                 WORKTREE_GLYPH)
                x += fm.horizontalAdvance(WORKTREE_GLYPH)
                painter.setPen(QPen(line_color))
                painter.drawText(slot.adjusted(x, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, rest)
            else:
                painter.drawText(slot, Qt.AlignLeft | Qt.AlignVCenter, text)
            if pri:
                painter.setPen(QPen(current_accent(index.row())))
                painter.drawText(slot.adjusted(fm.horizontalAdvance(text), 0, 0, 0),
                                 Qt.AlignLeft | Qt.AlignVCenter, fm.elidedText(pri, Qt.ElideRight, text_w))

        # Subagent twinkle — paints whenever subagents > 0, independent of
        # the main turn's working state. Sits one slot inboard of the
        # main-turn glyph (or in the outboard slot when no main-turn glyph
        # is showing). Advances at 1/SUBAGENT_SLOWDOWN the spinner rate and
        # cycles same-center star glyphs in solarized cyan, so it reads as a
        # slow bloom of parallel work next to the faster braille spinner.
        if show_subagent:
            tw_font = QFont(option.font)
            tw_font.setPointSizeF(option.font.pointSizeF() * GLYPH_FONT_SCALE)
            tw_font.setBold(True)
            painter.setFont(tw_font)
            painter.setPen(QPen(self.SUBAGENT_COLOR))
            frame = SUBAGENT_FRAMES[
                (self.spinner_frame // SUBAGENT_SLOWDOWN) % len(SUBAGENT_FRAMES)
            ]
            slot = 2 if show_right_glyph else 1
            tw_rect = QRect(
                rect.right() - slot * BADGE_COL_W, rect.top(),
                BADGE_COL_W, rect.height(),
            )
            painter.drawText(tw_rect, Qt.AlignHCenter | Qt.AlignVCenter, frame)

        if not show_right_glyph:
            painter.restore()
            return

        # Right-edge glyph priority (highest first):
        #   alert dots — permission, answer, error, usage limit (so a
        #     permission prompt is glanceable even with desktop
        #     notifications off)
        #   compaction glyph
        #   working spinner (main turn active)
        #   DONE dot — never coincides with working or compaction, since
        #     Stop clears both before setting done
        #   ambient terminal-state mark (no Claude alert at all)
        alert = bool(status) and status != STATUS_DONE
        if compacting and not alert:
            c_font = QFont(option.font)
            c_font.setPointSizeF(option.font.pointSizeF() * GLYPH_FONT_SCALE)
            c_font.setBold(True)
            painter.setFont(c_font)
            painter.setPen(QPen(self.COMPACT_COLOR))
            c_rect = QRect(rect.right() - BADGE_COL_W, rect.top(), BADGE_COL_W, rect.height())
            painter.drawText(c_rect, Qt.AlignRight | Qt.AlignVCenter, self.COMPACT_GLYPH)
        elif working and not alert:
            spin_font = QFont(option.font)
            spin_font.setPointSizeF(option.font.pointSizeF() * GLYPH_FONT_SCALE)
            spin_font.setBold(True)
            painter.setFont(spin_font)
            painter.setPen(QPen(self.SPINNER_COLOR))
            frames = spinner_for_id(repo.id)
            frame = frames[self.spinner_frame % len(frames)]
            spin_rect = QRect(rect.right() - BADGE_COL_W, rect.top(), BADGE_COL_W, rect.height())
            painter.drawText(spin_rect, Qt.AlignRight | Qt.AlignVCenter, frame)
        else:
            color = self.STATUS_COLORS.get(status)
            if color is not None:
                dot_d = 10
                scale = self.pop_scale.get(repo.id, 1.0)
                if scale != 1.0:
                    # Grow the badge from its center. Both styles sit
                    # right-aligned, so the dot's center serves the glyph too.
                    center = QPoint(rect.right() - dot_d // 2, rect.center().y())
                    painter.translate(center)
                    painter.scale(scale, scale)
                    painter.translate(-center)
                if self.badge_style == "glyph":
                    glyph = self.STATUS_GLYPHS.get(status, "")
                    g_font = QFont(option.font)
                    g_font.setPointSizeF(option.font.pointSizeF() * GLYPH_FONT_SCALE)
                    g_font.setBold(True)
                    painter.setFont(g_font)
                    painter.setPen(QPen(color))
                    g_rect = QRect(rect.right() - self.GLYPH_W, rect.top(),
                                   self.GLYPH_W, rect.height())
                    painter.drawText(g_rect, Qt.AlignRight | Qt.AlignVCenter, glyph)
                else:
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
                # when no working spinner and no DONE/ATTENTION dot owns
                # the column.
                a_font = QFont(option.font)
                a_font.setPointSizeF(option.font.pointSizeF() * GLYPH_FONT_SCALE)
                painter.setFont(a_font)
                painter.setPen(QPen(self.AMBIENT_COLOR))
                a_rect = QRect(rect.right() - BADGE_COL_W, rect.top(), BADGE_COL_W, rect.height())
                painter.drawText(a_rect, Qt.AlignRight | Qt.AlignVCenter, ambient_glyph)

        painter.restore()
