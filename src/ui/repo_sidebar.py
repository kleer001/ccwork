"""Left-hand repo list with per-row name / branch / unread badge."""

from __future__ import annotations

import os
import shutil
import time
import zlib
from dataclasses import dataclass

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QPoint,
    QProcess,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core import repo_store
from src.core.hook_server import EVENT_NOTIFICATION, EVENT_STOP
from src.core.repo_store import Repo, RepoStore
from src.ui.arrangement_animator import ArrangementAnimator

# Custom roles — keep the model backed by a single Repo per row plus branch
# + status. The view's delegate reads these directly. STATUS is one of:
# "" (no badge), "done" (Claude finished a turn), "attention" (Claude needs
# input). Color-coded by the delegate.
ROLE_REPO    = Qt.UserRole + 1
ROLE_BRANCH  = Qt.UserRole + 2
ROLE_STATUS  = Qt.UserRole + 3
ROLE_WORKING = Qt.UserRole + 4  # bool — Claude mid-turn in this repo
ROLE_HAS_TERMINAL = Qt.UserRole + 5  # bool — a TerminalHost exists for this repo this session

@dataclass(frozen=True)
class StatusDefinition:
    """Single source of truth for a row-status: tooltip label + badge paint.

    `color`/`glyph` of None means the status does not paint in the right-edge
    badge column (it may paint elsewhere, e.g. as a left-edge stripe).
    `claude_activity` distinguishes Claude-driven statuses (which stamp the
    auto-arrange recency timestamp) from user-state cues (which do not).
    """
    value: str
    label: str
    color: QColor | None
    glyph: str | None
    claude_activity: bool = False


# Solarized-ish palette: red = needs attention (urgent), green = done (calmer).
STATUS_DONE_DEF = StatusDefinition(
    value="done",
    label="Claude finished a turn",
    color=QColor(133, 153, 0),
    glyph="✓",
    claude_activity=True,
)
STATUS_ATTENTION_DEF = StatusDefinition(
    value="attention",
    label="Claude needs input",
    color=QColor(220, 50, 47),
    glyph="!",
    claude_activity=True,
)
# `last_focused` paints as a left-edge stripe, not a right-edge badge — so the
# badge column stays reserved for genuine Claude alerts.
STATUS_LAST_FOCUSED_DEF = StatusDefinition(
    value="last_focused",
    label="Last focused",
    color=None,
    glyph=None,
)

_ALL_STATUSES = (STATUS_DONE_DEF, STATUS_ATTENTION_DEF, STATUS_LAST_FOCUSED_DEF)

STATUS_DONE         = STATUS_DONE_DEF.value
STATUS_ATTENTION    = STATUS_ATTENTION_DEF.value
STATUS_LAST_FOCUSED = STATUS_LAST_FOCUSED_DEF.value

STATUS_LABELS = {s.value: s.label for s in _ALL_STATUSES if s.label}
CLAUDE_ACTIVITY_STATUSES = frozenset(s.value for s in _ALL_STATUSES if s.claude_activity)
WORKING_LABEL = "Claude is working…"

# Hook event → sidebar status. Hook events that don't map to a status
# (UserPromptSubmit, RepoAdded) are simply absent.
EVENT_TO_STATUS = {
    EVENT_STOP:         STATUS_DONE,
    EVENT_NOTIFICATION: STATUS_ATTENTION,
}


# Five braille spinner variants. Each repo gets one deterministically
# (crc32 of repo.id mod len) so the sidebar feels lightly varied without
# being noisy — the same repo always animates the same way.
SPINNER_VARIANTS: tuple[tuple[str, ...], ...] = (
    ("⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"),                  # classic rotating
    ("⠋","⠙","⠚","⠞","⠖","⠦","⠴","⠲","⠳","⠓"),                  # rolling wave
    ("⠄","⠆","⠇","⠦","⠴","⠼","⠸","⠰","⠠","⠰","⠸","⠼","⠴","⠦","⠇","⠆"),  # bouncing trio
    ("⣀","⣄","⣤","⣦","⣶","⣷","⣿","⣷","⣶","⣦","⣤","⣄"),          # pulse fill
    ("⠄","⠆","⠇","⠋","⠙","⠸","⠰","⠠","⠰","⠸","⠙","⠋","⠇","⠆"),  # center bounce
)
SPINNER_INTERVAL_MS = 100


def spinner_for_id(repo_id: str) -> tuple[str, ...]:
    """Pick a stable spinner variant for `repo_id`.

    crc32 (zlib stdlib) is used instead of Python's built-in `hash` because
    the latter is salted per-process — the variant would change on every
    launch, which would feel like a bug.
    """
    return SPINNER_VARIANTS[zlib.crc32(repo_id.encode("utf-8")) % len(SPINNER_VARIANTS)]

# 25 glyphs commonly used to tag software-project work. Click-to-pick in
# the badge dialog; not exhaustive — the line edit accepts any character.
BADGE_GALLERY = (
    "🐛", "🧪", "🚀", "🔧", "🎨",
    "📦", "🔥", "⚡", "✨", "📝",
    "🔒", "🌟", "🏗️", "🎯", "🔍",
    "💡", "⚙️", "🐳", "🌿", "🔬",
    "🛠️", "📊", "🧹", "🗃️", "🎬",
)

# External one-shot emoji pickers tried in order. First found wins; the
# rest depend on the user's desktop. Fallback path is the line edit's own
# OS-level shortcut (Ctrl+. / Ctrl+;).
EMOJI_PICKER_CANDIDATES = (
    "bemoji", "rofimoji", "gnome-characters", "gucharmap", "kcharselect",
)


def _find_emoji_picker() -> str | None:
    for cmd in EMOJI_PICKER_CANDIDATES:
        path = shutil.which(cmd)
        if path:
            return path
    return None


class RepoListModel(QAbstractListModel):
    """Model backed by a RepoStore plus per-repo branch + unread counters."""

    def __init__(self, store: RepoStore, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        # _branches and _status broadcast across duplicate rows for the
        # same path — that's the intended UX (one path, one branch / one
        # status). They stay path-keyed.
        self._branches: dict[str, str | None] = {}
        self._status: dict[str, str] = {}
        # _working and _last_activity are per-instance: each duplicate
        # row tracks its own session state. Keyed by repo.id. Hook
        # dispatch fans path → ids in `set_working` / `set_status`.
        self._working: set[str] = set()
        # Repo ids whose TerminalHost has been spawned in the current ccwork
        # session. Drives the visual difference between "touched" rows (bold
        # upright) and "untouched" rows (regular italic). Cleared on terminal
        # exit so a closed-then-not-reopened repo reverts to italic.
        self._active_ids: set[str] = set()
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
            return repo.id in self._working
        if role == ROLE_HAS_TERMINAL:
            return repo.id in self._active_ids
        if role == Qt.ToolTipRole:
            # Prepend a human-readable status line so hovering a row tells
            # the user what the badge means without having to memorize the
            # color palette. Path stays as the second line for context.
            if repo.id in self._working:
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
        return self._store.index_of(path)

    def indices_of(self, path: str) -> list[int]:
        return self._store.indices_of(path)

    def index_of_id(self, repo_id: str) -> int:
        return self._store.index_of_id(repo_id)

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

    def refresh_branch(self, path: str) -> None:
        """Recompute branch subtitle for a single repo. One git call.

        Click handlers use this instead of refresh_branches() so click
        latency stays O(1) regardless of repo count — at 30+ repos the
        full sweep was spawning 30+ `git symbolic-ref` subprocesses per
        click.
        """
        new = repo_store.current_branch(path)
        if self._branches.get(path) == new:
            return
        self._branches[path] = new
        self._emit_changed_for_path(path, [ROLE_BRANCH])

    def set_status(self, path: str, status: str) -> None:
        """Set the per-repo status badge ("done", "attention", or "" to clear).

        Per-path state — every duplicate row for this path repaints together.
        Claude-activity statuses also stamp `_last_activity` for every id
        matching the path (per-id, so the auto-arrange sort can look up by
        repo.id without re-resolving paths).
        """
        if status:
            self._status[path] = status
        else:
            self._status.pop(path, None)
        if status in CLAUDE_ACTIVITY_STATUSES:
            now = time.monotonic()
            for r in self._store.repos_for_path(path):
                self._last_activity[r.id] = now
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
        """Toggle the spinner for every duplicate row matching `path`.

        Hook events arrive cwd-keyed; we fan out to every id sharing that
        cwd because hooks can't tell duplicates apart by path alone.
        Per-instance state is keyed by repo.id under the hood — see
        `set_working_for_id` for single-instance updates (used by
        terminal-finished cleanup, where we know the exact id).
        """
        ids = [r.id for r in self._store.repos_for_path(path)]
        if not ids:
            return
        now = time.monotonic()
        changed = False
        for repo_id in ids:
            was = repo_id in self._working
            if working == was:
                continue
            if working:
                self._working.add(repo_id)
                self._last_activity[repo_id] = now
            else:
                self._working.discard(repo_id)
            changed = True
        if changed:
            self._emit_changed_for_path(path, [ROLE_WORKING])

    def set_working_for_id(self, repo_id: str, working: bool) -> None:
        """Toggle the spinner for one specific instance.

        Used when the caller knows the exact id (e.g. terminal exit) and
        wants to leave sibling duplicates' state untouched.
        """
        was = repo_id in self._working
        if working == was:
            return
        if working:
            self._working.add(repo_id)
            self._last_activity[repo_id] = time.monotonic()
        else:
            self._working.discard(repo_id)
        row = self.index_of_id(repo_id)
        if row >= 0:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [ROLE_WORKING])

    def is_working(self, repo_id: str) -> bool:
        return repo_id in self._working

    def any_working(self) -> bool:
        return bool(self._working)

    def working_rows(self) -> list[int]:
        """Row indices currently in the working state.

        Used by the spinner repaint loop. The set of working ids is
        usually 0–2; resolving them to row indices in O(N) is fine
        because rows don't move during a spin tick. The previous
        approach iterated *every* row asking ROLE_WORKING — at 50 repos
        × 10 Hz that was 500 dict-membership checks/sec for nothing.
        """
        if not self._working:
            return []
        rows: list[int] = []
        for i, r in enumerate(self._store.repos):
            if r.id in self._working:
                rows.append(i)
        return rows

    def set_emoji(self, repo_id: str, emoji: str) -> None:
        """Set or clear the optional leading emoji for one row.

        Per-id, not per-path: duplicates on the same path tag independently.
        Persists immediately and repaints the row's display name.
        """
        repo = self._store.find_by_id(repo_id)
        if repo is None or repo.emoji == emoji:
            return
        repo.emoji = emoji
        self._store.save()
        row = self.index_of_id(repo_id)
        if row >= 0:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [Qt.DisplayRole])

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
        """Most-recent activity timestamp across every duplicate of `path`.

        Activity is stored per-id; this aggregator preserves the
        path-based public query the auto-arrange tests use.
        """
        ts = 0.0
        for r in self._store.repos_for_path(path):
            ts = max(ts, self._last_activity.get(r.id, 0.0))
        return ts

    # Sort keys consumed by both the instant reorder (`apply_*`) and the
    # animated preview (`target_order_ids`). Defined here so both code paths
    # cannot drift.
    def _activity_key(self, item):
        i, r = item
        ts = self._last_activity.get(r.id, 0.0)
        return (-ts if ts > 0 else float("inf"), i)

    def _grouping_key(self, item):
        i, r = item
        return (0 if r.id in self._active_ids else 1, i)

    @staticmethod
    def _stable_sort(repos: list[Repo], key) -> list[Repo]:
        indexed = list(enumerate(repos))
        indexed.sort(key=key)
        return [r for _, r in indexed]

    def apply_auto_arrange(self) -> bool:
        """Reorder _store.repos by Claude-activity recency desc.

        Repos with no recorded activity sort to the bottom in their
        current relative order (stable). Returns True if the order
        changed. Selection survives via persistent indices.
        """
        return self._reorder_by(self._activity_key)

    def apply_terminal_grouping(self) -> bool:
        """Float repos with a live terminal to the top of the list.

        Stable within each group: relative order is preserved, so this
        composes cleanly after apply_auto_arrange.
        """
        return self._reorder_by(self._grouping_key)

    def target_order_ids(
        self, *, auto_arrange: bool, group_active: bool
    ) -> list[str]:
        """The id sequence the composition of auto-arrange and grouping
        would produce — read-only preview, no model mutation.

        Mirrors the sequential-stable-sort composition used by the instant
        `apply_auto_arrange()` + `apply_terminal_grouping()` chain: activity
        first, grouping on top. With both flags off, returns the current
        order (target == current, no animation work).
        """
        repos = list(self._store.repos)
        if auto_arrange:
            repos = self._stable_sort(repos, self._activity_key)
        if group_active:
            repos = self._stable_sort(repos, self._grouping_key)
        return [r.id for r in repos]

    def move_row_up(self, row: int) -> bool:
        """Swap `row` with `row-1` via beginMoveRows. The single primitive
        the bubble-up animation builds on.
        """
        if row <= 0 or row >= len(self._store.repos):
            return False
        if not self.beginMoveRows(QModelIndex(), row, row, QModelIndex(), row - 1):
            return False
        repos = self._store.repos
        repos[row - 1], repos[row] = repos[row], repos[row - 1]
        self.endMoveRows()
        return True

    def _reorder_by(self, sort_key) -> bool:
        repos = list(self._store.repos)
        if len(repos) <= 1:
            return False
        indexed = list(enumerate(repos))
        indexed.sort(key=sort_key)
        new_order = [r for _, r in indexed]
        if new_order == repos:
            return False

        self.layoutAboutToBeChanged.emit()
        old_persistent = list(self.persistentIndexList())
        # Use repo.id (unique) — paths can repeat across duplicate rows.
        new_row_for_id = {r.id: i for i, r in enumerate(new_order)}
        self._store.repos[:] = new_order
        new_persistent = []
        for p in old_persistent:
            if not p.isValid():
                new_persistent.append(QModelIndex())
                continue
            old_row = p.row()
            if 0 <= old_row < len(repos):
                rid = repos[old_row].id
                new_row = new_row_for_id.get(rid, -1)
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

        # Per-id state always drops — the row is gone for good.
        self._active_ids.discard(repo.id)
        self._working.discard(repo.id)
        self._last_activity.pop(repo.id, None)
        # Path-keyed state stays only while at least one row still uses
        # the path — drop it once the last duplicate is gone.
        if not self._store.repos_for_path(path):
            self._branches.pop(path, None)
            self._status.pop(path, None)
        self._store.save()
        return True


class RepoDelegate(QStyledItemDelegate):
    """Two-line row: name (bold) + branch (subtitle), unread badge right-aligned."""

    ROW_HEIGHT = 52
    PADDING_X = 10
    # Vertical gap painted *above* the first inactive (no-terminal) row
    # when ui.group_active_repos is on. Thin strip of widget background,
    # outside any row's border, so the two groups read as separate clusters.
    GROUP_GAP_H = 10
    # Right-edge glyph column (status dot or spinner). Reserved whenever the
    # row has a status to show — text elides to fit. The badge is a
    # first-class UI element: glance-state matters more than seeing an
    # extra character or two of the repo name on a very narrow sidebar.
    GLYPH_W = 14
    GLYPH_GAP = 4
    # Derived from _ALL_STATUSES — statuses with color=None (e.g. last_focused)
    # are excluded so the right-edge badge column stays reserved for genuine
    # Claude alerts (working / done / attention).
    STATUS_COLORS = {s.value: s.color for s in _ALL_STATUSES if s.color is not None}
    STATUS_GLYPHS = {s.value: s.glyph for s in _ALL_STATUSES if s.glyph is not None}
    # Muted blue for the working spinner — distinct from the red/green
    # status dots so glance-state is unambiguous.
    SPINNER_COLOR = QColor(38, 139, 210)  # solarized blue

    # Base hue for the "last focused" left-edge stripe (solarized violet).
    # Modulated per-theme by _last_focused_stripe_color so it stays subtle.
    LAST_FOCUSED_BASE = QColor(108, 113, 196)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Advanced by RepoSidebar's QTimer; read every paint.
        self.spinner_frame = 0
        # "dot" or "glyph". Toggled live by RepoSidebar.set_badge_style.
        self.badge_style = "dot"
        # Mirrors ui.group_active_repos. RepoSidebar keeps it in sync.
        self.group_enabled = False

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

    # Left-edge stripe width for the active/selected row. Thin enough to
    # not crowd the text, thick enough to read at a glance.
    ACTIVE_STRIPE_W = 3
    # Last-focused stripe sits in the same left column but slightly thinner
    # so the active stripe still reads as the dominant cue when both apply.
    LAST_FOCUSED_STRIPE_W = 2

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

        # Last-focused bookmark: thin left-edge stripe instead of a right-edge
        # dot, so the badge column stays reserved for genuine Claude alerts.
        # Skip when the row is selected — the active stripe owns that edge.
        if not selected and status == STATUS_LAST_FOCUSED:
            lf_rect = QRect(
                option.rect.left(), option.rect.top(),
                self.LAST_FOCUSED_STRIPE_W, option.rect.height(),
            )
            painter.fillRect(lf_rect, self._last_focused_stripe_color(option.palette))

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
            frames = spinner_for_id(repo.id)
            frame = frames[self.spinner_frame % len(frames)]
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
        # Reshuffle animation lives in its own object so it can be tested
        # without a QListView and the sidebar widget can focus on
        # rendering + selection. The animator owns four timers and the
        # quiet-window state machine.
        self._animator = ArrangementAnimator(
            self._model, lambda: self._settings, parent=self,
        )
        self._view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._view.setSelectionMode(QAbstractItemView.SingleSelection)
        # Per-row sizeHint: the group-boundary row is taller than the rest
        # to make room for the inter-group gap. Uniform sizes would skip the
        # delegate's per-index sizeHint call entirely.
        self._view.setUniformItemSizes(False)
        # Mirror the initial pref into the delegate so the first paint after
        # construction already shows the right grouping behavior.
        if settings is not None:
            self._delegate.group_enabled = bool(
                getattr(settings.ui, "group_active_repos", False)
            )
        self._view.selectionModel().currentChanged.connect(self._on_current_changed)
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        # Mouse tracking + event filter: catches hover-without-click so
        # we know the cursor is over the sidebar even before any button
        # is pressed. Without setMouseTracking, MouseMove fires only
        # while a button is held.
        self._view.setMouseTracking(True)
        self._view.viewport().setMouseTracking(True)
        self._view.installEventFilter(self)
        self._view.viewport().installEventFilter(self)

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

    def refresh_branch(self, path: str) -> None:
        self._model.refresh_branch(path)

    def set_status(self, path: str, status: str) -> None:
        self._model.set_status(path, status)
        if status in CLAUDE_ACTIVITY_STATUSES:
            self._animator.schedule_reorder()

    def clear_status(self, path: str) -> None:
        self._model.clear_status(path)

    def set_last_focused(self, path: str) -> None:
        self._model.set_last_focused(path)

    def set_settings(self, settings) -> None:
        """Swap in a fresh Settings reference (called after Preferences edits)."""
        self._settings = settings
        new_group = bool(getattr(settings.ui, "group_active_repos", False))
        if self._delegate.group_enabled != new_group:
            self._delegate.group_enabled = new_group
            # Re-apply grouping so rows already shift; if turning OFF, the
            # current order is preserved (we never auto-revert) but the gap
            # disappears. Either way, sizeHints must be re-queried.
            if new_group:
                self._model.apply_terminal_grouping()
            self._view.scheduleDelayedItemsLayout()
            self._view.viewport().update()

    def set_terminal_active(self, repo_id: str, active: bool) -> None:
        """Mark a row as having a live terminal and queue a re-group.

        We deliberately do NOT reshuffle right now: the row whose terminal
        just spawned is the row the user just clicked, and yanking it out
        from under the cursor reads as "the wrong repo got selected." The
        animator's quiet-window gate defers until the user has actually
        engaged with a terminal; until then this just queues a walk.
        Same applies on terminal close.
        """
        self._model.set_terminal_active(repo_id, active)
        # Only the grouping path produces variable-height boundary rows.
        # When grouping is off, every row is ROW_HEIGHT and sizeHints
        # don't need re-querying.
        if self._delegate.group_enabled:
            self._view.scheduleDelayedItemsLayout()
        if self._settings is not None and getattr(
            self._settings.ui, "group_active_repos", False
        ):
            self._animator.request_walk()

    # Activity sources we care about. Hover/move catches "cursor is on
    # the sidebar" even without a click, which is the visual state that
    # made the original yank-under-cursor problem feel wrong.
    _ACTIVITY_EVENTS = frozenset({
        QEvent.MouseMove,
        QEvent.MouseButtonPress,
        QEvent.Enter,
        QEvent.HoverEnter,
        QEvent.HoverMove,
        QEvent.KeyPress,
        QEvent.Wheel,
        QEvent.FocusIn,
    })

    def eventFilter(self, obj, event):  # type: ignore[override]
        if event.type() in self._ACTIVITY_EVENTS and (
            obj is self._view or obj is self._view.viewport()
        ):
            self._animator.bump_activity()
        return super().eventFilter(obj, event)

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
        self._refresh_spinner_timer()
        if working:
            self._animator.schedule_reorder()

    def set_working_for_id(self, repo_id: str, working: bool) -> None:
        self._model.set_working_for_id(repo_id, working)
        self._refresh_spinner_timer()
        if working:
            self._animator.schedule_reorder()

    def _refresh_spinner_timer(self) -> None:
        if self._model.any_working():
            if not self._spinner_timer.isActive():
                self._spinner_timer.start()
        else:
            self._spinner_timer.stop()

    def branch_for(self, path: str) -> str | None:
        """Cached branch name for the first row matching `path`, or None."""
        row = self._model.index_of(path)
        if row < 0:
            return None
        return self._model.data(self._model.index(row), ROLE_BRANCH)

    def open_add_dialog(self) -> None:
        """Public entry-point for the Ctrl+O / + Add Repo flow."""
        self._on_add_clicked()

    def confirm_reload(self, repo: Repo) -> None:
        """Public entry-point for the terminal-context-menu reload flow."""
        self._confirm_reload(repo)

    def _advance_spinner(self) -> None:
        self._delegate.spinner_frame += 1
        for row in self._model.working_rows():
            self._view.update(self._model.index(row))

    # ── signals ──

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        # Selection change is a strong "user is on the sidebar" signal —
        # arguably stronger than mouse hover. Push the quiet deadline.
        self._animator.bump_activity()
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
        self.select_id(added.id)
        self.repo_added.emit(added)

    def _on_context_menu(self, pos: QPoint) -> None:
        self._animator.bump_activity()
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
        set_badge_act = QAction("Set badge…", menu)
        set_badge_act.setToolTip("Prefix the row with a glyph (emoji or any single character).")
        set_badge_act.triggered.connect(lambda _=False, r=repo: self._prompt_badge(r))
        menu.addAction(set_badge_act)

        clear_badge_act = QAction("Clear badge", menu)
        clear_badge_act.setEnabled(bool(repo.emoji))
        clear_badge_act.triggered.connect(lambda _=False, r=repo: self._model.set_emoji(r.id, ""))
        menu.addAction(clear_badge_act)

        menu.addSeparator()
        remove_act = QAction("Remove from sidebar", menu)
        remove_act.triggered.connect(lambda _=False, r=repo, row=idx.row(): self._confirm_remove(r, row))
        menu.addAction(remove_act)

        menu.exec(self._view.viewport().mapToGlobal(pos))

    def _prompt_badge(self, repo: Repo) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Set badge")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(f"Badge for {repo.display_name}:"))
        layout.addWidget(QLabel("Click a glyph below, or type/paste your own."))

        edit = QLineEdit(repo.emoji, dlg)

        # 5×5 click-to-pick gallery. Populates the line edit; OK confirms.
        gallery = QGridLayout()
        gallery.setSpacing(2)
        gallery_font = QFont()
        gallery_font.setPointSize(gallery_font.pointSize() + 4)
        for i, glyph in enumerate(BADGE_GALLERY):
            btn = QToolButton(dlg)
            btn.setText(glyph)
            btn.setFont(gallery_font)
            btn.setAutoRaise(True)
            btn.setFixedSize(36, 36)
            btn.clicked.connect(lambda _=False, g=glyph: edit.setText(g))
            gallery.addWidget(btn, i // 5, i % 5)
        layout.addLayout(gallery)

        # Custom-input row: line edit + system picker launcher.
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        picker = _find_emoji_picker()
        browse_btn = QPushButton("Browse system…", dlg)
        if picker is None:
            browse_btn.setEnabled(False)
            browse_btn.setToolTip(
                "No system emoji picker found. Install one of: "
                + ", ".join(EMOJI_PICKER_CANDIDATES)
            )
        else:
            browse_btn.setToolTip(
                f"Launches {os.path.basename(picker)}. "
                "Most pickers copy to the clipboard — paste here with Ctrl+V."
            )
            browse_btn.clicked.connect(lambda _=False, p=picker: QProcess.startDetached(p, []))
        row.addWidget(browse_btn)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        edit.setFocus()
        if dlg.exec() == QDialog.Accepted:
            self._model.set_emoji(repo.id, edit.text().strip())

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
