"""Left-hand repo list with per-row name / branch / unread badge."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from src.core import repo_store
from src.core.repo_store import Repo, RepoStore


# Custom roles — keep the model backed by a single Repo per row plus branch
# + status. The view's delegate reads these directly. STATUS is one of:
# "" (no badge), "done" (Claude finished a turn), "attention" (Claude needs
# input). Color-coded by the delegate.
ROLE_REPO    = Qt.UserRole + 1
ROLE_BRANCH  = Qt.UserRole + 2
ROLE_STATUS  = Qt.UserRole + 3
ROLE_WORKING = Qt.UserRole + 4  # bool — Claude mid-turn in this repo
ROLE_HAS_TERMINAL = Qt.UserRole + 5  # bool — a TerminalHost exists for this repo this session

STATUS_DONE          = "done"
STATUS_ATTENTION     = "attention"
STATUS_LAST_FOCUSED  = "last_focused"

# Human-readable labels for the row tooltip — paired with the colored badge
# so users don't have to memorize the dot palette.
STATUS_LABELS = {
    STATUS_ATTENTION:    "Claude needs input",
    STATUS_DONE:         "Claude finished a turn",
    STATUS_LAST_FOCUSED: "Last focused",
}
WORKING_LABEL = "Claude is working…"


def _norm(path: str) -> str:
    """Canonicalize a path so set-membership checks agree no matter how the
    path was supplied (trailing slash, symlink, relative segment).

    Used as the single key shape for `_working`. Without this, a hook that
    reports `/symlink/repo` while the sidebar holds `/real/repo` would
    silently fail to flip the spinner on — the bug we hit while clicking
    off a working repo.
    """
    return os.path.realpath(path) if path else ""

# Standard 10-frame braille spinner. Advanced by a QTimer on the sidebar.
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_INTERVAL_MS = 100


class RepoListModel(QAbstractListModel):
    """Model backed by a RepoStore plus per-repo branch + unread counters."""

    def __init__(self, store: RepoStore, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._branches: dict[str, str | None] = {}
        self._status: dict[str, str] = {}
        self._working: set[str] = set()
        # Repo ids whose TerminalHost has been spawned in the current ccwork
        # session. Drives the visual difference between "touched" rows (bold
        # upright) and "untouched" rows (regular italic). Cleared on terminal
        # exit so a closed-then-not-reopened repo reverts to italic.
        self._active_ids: set[str] = set()
        # Per-repo timestamp of the last Claude-driven event
        # (Stop / Notification / UserPromptSubmit). Feeds the optional
        # auto-arrange sort. STATUS_LAST_FOCUSED is user navigation, not
        # Claude activity, and does not stamp this dict.
        self._last_activity: dict[str, float] = {}

    # ── Qt model API ──

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._store.repos)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._store.repos):
            return None
        repo = self._store.repos[index.row()]
        if role == Qt.DisplayRole:
            return repo.display_name
        if role == ROLE_REPO:
            return repo
        if role == ROLE_BRANCH:
            return self._branches.get(repo.path)
        if role == ROLE_STATUS:
            return self._status.get(repo.path, "")
        if role == ROLE_WORKING:
            return _norm(repo.path) in self._working
        if role == ROLE_HAS_TERMINAL:
            return repo.id in self._active_ids
        if role == Qt.ToolTipRole:
            # Prepend a human-readable status line so hovering a row tells
            # the user what the badge means without having to memorize the
            # color palette. Path stays as the second line for context.
            if _norm(repo.path) in self._working:
                return f"{WORKING_LABEL}\n{repo.path}"
            label = STATUS_LABELS.get(self._status.get(repo.path, ""))
            if label:
                return f"{label}\n{repo.path}"
            return repo.path
        return None

    # ── helpers ──

    def repo_at(self, row: int) -> Repo | None:
        if 0 <= row < len(self._store.repos):
            return self._store.repos[row]
        return None

    def index_of(self, path: str) -> int:
        """First row whose realpath matches `path`. With duplicate repos there
        can be several; callers that need every match use `indices_of`."""
        real = os.path.realpath(path)
        for i, r in enumerate(self._store.repos):
            if os.path.realpath(r.path) == real:
                return i
        return -1

    def indices_of(self, path: str) -> list[int]:
        """All rows whose realpath matches `path`."""
        real = os.path.realpath(path)
        return [i for i, r in enumerate(self._store.repos)
                if os.path.realpath(r.path) == real]

    def index_of_id(self, repo_id: str) -> int:
        for i, r in enumerate(self._store.repos):
            if r.id == repo_id:
                return i
        return -1

    def _emit_changed_for_path(self, path: str, roles: list[int]) -> None:
        """dataChanged for every row matching `path` (for broadcast updates)."""
        for row in self.indices_of(path):
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, roles)

    def refresh_branches(self) -> None:
        """Recompute branch subtitle for every repo. Call on focus/refresh."""
        changed = False
        for r in self._store.repos:
            new = repo_store.current_branch(r.path)
            if self._branches.get(r.path) != new:
                self._branches[r.path] = new
                changed = True
        if changed and self._store.repos:
            top = self.index(0)
            bot = self.index(len(self._store.repos) - 1)
            self.dataChanged.emit(top, bot, [ROLE_BRANCH])

    def set_status(self, path: str, status: str) -> None:
        """Set the per-repo status badge ("done", "attention", or "" to clear).

        Per-path state — every duplicate row for this path repaints together.
        """
        if status:
            self._status[path] = status
        else:
            self._status.pop(path, None)
        if status in (STATUS_DONE, STATUS_ATTENTION):
            self._last_activity[path] = time.monotonic()
        self._emit_changed_for_path(path, [ROLE_STATUS])

    def clear_status(self, path: str) -> None:
        self.set_status(path, "")

    def set_last_focused(self, path: str) -> None:
        """Mark `path` as the most-recently-focused repo.

        Lower priority than Stop/Notification: if the row already has one of
        those status dots, it stays — Claude-side signals matter more than
        "you were here." The violet dot only lights on rows whose status is
        otherwise empty. Also clears LAST_FOCUSED from any other row so the
        dot is unique.
        """
        # Strip prior last-focused from any other row.
        for other in [p for p, s in self._status.items()
                      if s == STATUS_LAST_FOCUSED and p != path]:
            self.clear_status(other)
        # Only set on the target if nothing higher-priority is there.
        if not self._status.get(path):
            self.set_status(path, STATUS_LAST_FOCUSED)

    def set_working(self, path: str, working: bool) -> None:
        """Toggle the spinner for `path`. No-op if state already matches.

        Per-path state — every duplicate row for this path spins together.
        """
        key = _norm(path)
        was = key in self._working
        if working == was:
            return
        if working:
            self._working.add(key)
            self._last_activity[path] = time.monotonic()
        else:
            self._working.discard(key)
        self._emit_changed_for_path(path, [ROLE_WORKING])

    def any_working(self) -> bool:
        return bool(self._working)

    def set_terminal_active(self, repo_id: str, active: bool) -> None:
        """Mark `repo_id` as having a live TerminalHost (or not).

        Per-id, not per-path: each duplicate row tracks independently so
        opening one duplicate's terminal doesn't unitalicize the other.
        """
        was = repo_id in self._active_ids
        if active == was:
            return
        if active:
            self._active_ids.add(repo_id)
        else:
            self._active_ids.discard(repo_id)
        row = self.index_of_id(repo_id)
        if row >= 0:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [ROLE_HAS_TERMINAL])

    def last_activity(self, path: str) -> float:
        return self._last_activity.get(path, 0.0)

    def apply_auto_arrange(self) -> bool:
        """Reorder _store.repos by Claude-activity recency desc.

        Repos with no recorded activity sort to the bottom in their
        current relative order (stable). Returns True if the order
        changed. Selection survives via persistent indices.
        """
        repos = list(self._store.repos)
        if len(repos) <= 1:
            return False
        indexed = list(enumerate(repos))

        def sort_key(item):
            i, r = item
            ts = self._last_activity.get(r.path, 0.0)
            # Higher ts → earlier. No-activity rows tie on +inf and
            # fall back to the original index → stable bottom group.
            return (-ts if ts > 0 else float("inf"), i)

        indexed.sort(key=sort_key)
        new_order = [r for _, r in indexed]
        if new_order == repos:
            return False

        self.layoutAboutToBeChanged.emit()
        old_persistent = list(self.persistentIndexList())
        new_row_for_path = {r.path: i for i, r in enumerate(new_order)}
        self._store.repos[:] = new_order
        new_persistent = []
        for p in old_persistent:
            if not p.isValid():
                new_persistent.append(QModelIndex())
                continue
            old_row = p.row()
            if 0 <= old_row < len(repos):
                path = repos[old_row].path
                new_row = new_row_for_path.get(path, -1)
                new_persistent.append(self.index(new_row) if new_row >= 0 else QModelIndex())
            else:
                new_persistent.append(QModelIndex())
        self.changePersistentIndexList(old_persistent, new_persistent)
        self.layoutChanged.emit()
        return True

    # ── add/remove piped from the store ──

    def reload(self) -> None:
        self.beginResetModel()
        self._store.load()
        self.endResetModel()

    def add_repo(self, path: str) -> Repo:
        """Append a new row for `path`. Always succeeds (duplicates allowed).

        If the add promoted an existing row from instance=0 to instance=1
        (going from 1→2 instances of the same path), that row's display name
        also changed — emit dataChanged for it so the sidebar repaints.
        """
        before_resolved = {r.id: r.instance for r in self._store.repos}
        repo = self._store.add(path)
        row = len(self._store.repos) - 1

        # If a sibling's instance changed (1→2 promotion), repaint that row.
        promoted_rows = [
            i for i, r in enumerate(self._store.repos[:-1])
            if before_resolved.get(r.id, r.instance) != r.instance
        ]

        self.beginInsertRows(QModelIndex(), row, row)
        self.endInsertRows()
        self._store.save()
        # Populate branch for the newly added row so the subtitle isn't
        # blank until the next focus-triggered refresh. Cheap: one git call.
        self._branches[repo.path] = repo_store.current_branch(repo.path)
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [ROLE_BRANCH])
        for r in promoted_rows:
            pidx = self.index(r)
            self.dataChanged.emit(pidx, pidx, [Qt.DisplayRole])
        return repo

    def remove_repo_at(self, row: int) -> bool:
        if not (0 <= row < len(self._store.repos)):
            return False
        repo = self._store.repos[row]
        path = repo.path
        before_instances = {r.id: r.instance for r in self._store.repos}
        self.beginRemoveRows(QModelIndex(), row, row)
        self._store.remove_by_id(repo.id)
        self.endRemoveRows()

        # If any survivor's instance changed (count dropped to 1 → instance
        # reset to 0), repaint that row so its suffix disappears.
        for i, r in enumerate(self._store.repos):
            if before_instances.get(r.id, r.instance) != r.instance:
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, [Qt.DisplayRole])

        # Per-path state stays only while at least one row still uses the
        # path — drop it once the last duplicate is gone.
        if not self._store.repos_for_path(path):
            self._branches.pop(path, None)
            self._status.pop(path, None)
            self._working.discard(_norm(path))
            self._last_activity.pop(path, None)
        self._store.save()
        return True


class RepoDelegate(QStyledItemDelegate):
    """Two-line row: name (bold) + branch (subtitle), unread badge right-aligned."""

    ROW_HEIGHT = 52
    PADDING_X = 10
    # Right-edge glyph column (status dot or spinner). Reserved whenever the
    # row has a status to show — text elides to fit. The badge is a
    # first-class UI element: glance-state matters more than seeing an
    # extra character or two of the repo name on a very narrow sidebar.
    GLYPH_W = 14
    GLYPH_GAP = 4
    # Solarized-ish: red = needs attention (urgent), green = done (calmer).
    STATUS_COLORS = {
        STATUS_ATTENTION:    QColor(220, 50, 47),   # solarized red
        STATUS_DONE:         QColor(133, 153, 0),   # solarized green
        STATUS_LAST_FOCUSED: QColor(108, 113, 196), # solarized violet
    }
    # Muted cyan for the working spinner — distinct from the red/green
    # status dots so glance-state is unambiguous.
    SPINNER_COLOR = QColor(38, 139, 210)  # solarized blue

    # Single-glyph variants of the badge — same column, more self-explanatory
    # than a colored circle. Stays color-coded for users who like the palette.
    STATUS_GLYPHS = {
        STATUS_ATTENTION:    "!",
        STATUS_DONE:         "✓",
        STATUS_LAST_FOCUSED: "·",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Advanced by RepoSidebar's QTimer; read every paint.
        self.spinner_frame = 0
        # "dot" or "glyph". Toggled live by RepoSidebar.set_badge_style.
        self.badge_style = "dot"

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    # Left-edge stripe width for the active/selected row. Thin enough to
    # not crowd the text, thick enough to read at a glance.
    ACTIVE_STRIPE_W = 3

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()

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

        rect = option.rect.adjusted(self.PADDING_X, 4, -self.PADDING_X, -4)

        # Reserve the right-edge glyph column whenever the row has a status
        # to show. Text elides to fit; the badge stays put.
        # Untouched-this-session rows render italic + regular weight so the
        # eye can pick out which repos already have a live terminal without
        # using color (which would compete with the status badge).
        name_font = QFont(option.font)
        name_font.setBold(has_terminal)
        name_font.setItalic(not has_terminal)
        show_glyph = working or (status in self.STATUS_COLORS)
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
        sub_text_raw = branch if branch else "(detached)" if repo else ""
        sub_rect = QRect(rect.left(), rect.top() + rect.height() // 2, text_w, rect.height() // 2)
        sub_text = painter.fontMetrics().elidedText(sub_text_raw, Qt.ElideRight, text_w)
        painter.drawText(sub_rect, Qt.AlignLeft | Qt.AlignVCenter, sub_text)

        if not show_glyph:
            painter.restore()
            return

        # Right-edge glyph: braille spinner when working (preempts dot), else
        # color-coded status dot. Working state is mutually exclusive with
        # done/attention in the hook flow — UserPromptSubmit clears status
        # before setting working; Stop/Notification clears working before
        # setting status.
        if working:
            spin_font = QFont(option.font)
            spin_font.setPointSizeF(option.font.pointSizeF() * 1.4)
            spin_font.setBold(True)
            painter.setFont(spin_font)
            painter.setPen(QPen(self.SPINNER_COLOR))
            frame = SPINNER_FRAMES[self.spinner_frame % len(SPINNER_FRAMES)]
            spin_rect = QRect(rect.right() - 16, rect.top(), 16, rect.height())
            painter.drawText(spin_rect, Qt.AlignRight | Qt.AlignVCenter, frame)
        else:
            color = self.STATUS_COLORS.get(status)
            if color is not None:
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

        painter.restore()


class RepoSidebar(QWidget):
    """The left-hand column: scrollable repo list + '+ Add Repo' at the bottom."""

    repo_selected = Signal(Repo)
    repo_added = Signal(Repo)
    repo_removed = Signal(Repo)  # emits the removed Repo (id needed to tear down)
    reload_requested = Signal(Repo)  # user asked to respawn the terminal

    def __init__(self, store: RepoStore, parent=None, settings=None) -> None:
        super().__init__(parent)
        self._store = store
        self._settings = settings
        self._model = RepoListModel(store, self)

        self._view = QListView(self)
        self._view.setModel(self._model)
        self._delegate = RepoDelegate(self._view)
        self._view.setItemDelegate(self._delegate)

        # Braille-spinner ticker. Only runs while at least one repo is in
        # the "working" state — otherwise it would repaint the viewport 10×
        # per second for no reason.
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(SPINNER_INTERVAL_MS)
        self._spinner_timer.timeout.connect(self._advance_spinner)
        # Debounced auto-arrange. Restarted on every Claude-driven event
        # while ui.auto_arrange_repos is True; fires once after 2s of
        # quiet to avoid reshuffling under the user's eye.
        self._reorder_timer = QTimer(self)
        self._reorder_timer.setSingleShot(True)
        self._reorder_timer.setInterval(2000)
        self._reorder_timer.timeout.connect(self._apply_auto_arrange)
        self._view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._view.setSelectionMode(QAbstractItemView.SingleSelection)
        self._view.setUniformItemSizes(True)
        self._view.selectionModel().currentChanged.connect(self._on_current_changed)
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)

        self._add_btn = QPushButton("+ Add Repo", self)
        self._add_btn.clicked.connect(self._on_add_clicked)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._view, 1)
        lay.addWidget(self._add_btn, 0)

        # Allow the splitter to drag the sidebar narrow. The status badge is
        # always reserved when present; text elides to fit.
        self.setMinimumWidth(60)
        self.setMaximumWidth(320)

        self._model.reload()
        self._model.refresh_branches()

    # ── public API ──

    @property
    def model(self) -> RepoListModel:
        return self._model

    def select_path(self, path: str) -> None:
        row = self._model.index_of(path)
        if row >= 0:
            idx = self._model.index(row)
            self._view.setCurrentIndex(idx)

    def select_id(self, repo_id: str) -> None:
        row = self._model.index_of_id(repo_id)
        if row >= 0:
            idx = self._model.index(row)
            self._view.setCurrentIndex(idx)

    def refresh_branches(self) -> None:
        self._model.refresh_branches()

    def set_status(self, path: str, status: str) -> None:
        self._model.set_status(path, status)
        if status in (STATUS_DONE, STATUS_ATTENTION):
            self._maybe_schedule_reorder()

    def clear_status(self, path: str) -> None:
        self._model.clear_status(path)

    def set_last_focused(self, path: str) -> None:
        self._model.set_last_focused(path)

    def set_settings(self, settings) -> None:
        """Swap in a fresh Settings reference (called after Preferences edits)."""
        self._settings = settings

    def set_badge_style(self, style: str) -> None:
        """Switch between the colored dot and single-glyph badge."""
        if style not in ("dot", "glyph"):
            return
        if self._delegate.badge_style == style:
            return
        self._delegate.badge_style = style
        self._view.viewport().update()

    def set_working(self, path: str, working: bool) -> None:
        self._model.set_working(path, working)
        if self._model.any_working():
            if not self._spinner_timer.isActive():
                self._spinner_timer.start()
        else:
            self._spinner_timer.stop()
        if working:
            self._maybe_schedule_reorder()

    def _maybe_schedule_reorder(self) -> None:
        if self._settings is None:
            return
        if not getattr(self._settings.ui, "auto_arrange_repos", False):
            return
        # QTimer.start() restarts an active single-shot timer — exactly
        # the debounce we want.
        self._reorder_timer.start()

    def _apply_auto_arrange(self) -> None:
        # Pref may have flipped off during the 2 s window — bail.
        if self._settings is None:
            return
        if not getattr(self._settings.ui, "auto_arrange_repos", False):
            return
        self._model.apply_auto_arrange()

    def _advance_spinner(self) -> None:
        self._delegate.spinner_frame += 1
        # Repaint only rows that are currently working.
        for row in range(self._model.rowCount()):
            idx = self._model.index(row)
            if idx.data(ROLE_WORKING):
                self._view.update(idx)

    # ── signals ──

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        # Mark the row we're leaving as "last focused" so the user can spot
        # where they were before. Subject to priority rules in
        # RepoListModel.set_last_focused — won't overwrite Stop/Notification.
        prev_repo = self._model.repo_at(previous.row()) if previous.isValid() else None
        if prev_repo is not None:
            self._model.set_last_focused(prev_repo.path)
        repo = self._model.repo_at(current.row()) if current.isValid() else None
        if repo is not None:
            self._model.clear_status(repo.path)
            self.repo_selected.emit(repo)

    def _on_add_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Add repo directory", os.path.expanduser("~"))
        if not path:
            return
        added = self._model.add_repo(path)
        # Select the just-added row by id (path may be ambiguous now that
        # duplicates are allowed).
        row = self._model.index_of_id(added.id)
        if row >= 0:
            self._view.setCurrentIndex(self._model.index(row))
        self.repo_added.emit(added)

    def _on_context_menu(self, pos: QPoint) -> None:
        idx = self._view.indexAt(pos)
        if not idx.isValid():
            return
        repo = self._model.repo_at(idx.row())
        if repo is None:
            return

        menu = QMenu(self)
        reload_act = QAction("Reload terminal", menu)
        reload_act.setToolTip("Respawn xterm to pick up new settings. Loses in-flight shell state.")
        reload_act.triggered.connect(lambda _=False, r=repo: self._confirm_reload(r))
        menu.addAction(reload_act)

        menu.addSeparator()
        remove_act = QAction("Remove from sidebar", menu)
        remove_act.triggered.connect(lambda _=False, r=repo, row=idx.row(): self._confirm_remove(r, row))
        menu.addAction(remove_act)

        menu.exec(self._view.viewport().mapToGlobal(pos))

    def _confirm_reload(self, repo: Repo) -> None:
        ans = QMessageBox.question(
            self,
            "Reload terminal",
            f"Respawn the terminal for {repo.display_name}?\n\n"
            "The running shell (and any active Claude session) will be killed. "
            "If Claude was mid-response, that response is lost — but the "
            "conversation transcript is preserved; run `claude --continue` "
            "to resume it.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            self.reload_requested.emit(repo)

    def _confirm_remove(self, repo: Repo, row: int) -> None:
        ans = QMessageBox.question(
            self,
            "Remove from sidebar",
            f"Remove {repo.display_name} from ccwork?\n\n"
            "The repo directory on disk is untouched — this only removes it "
            "from the sidebar list.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            self._model.remove_repo_at(row)
            self.repo_removed.emit(repo)
