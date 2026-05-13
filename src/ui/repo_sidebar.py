"""Left-hand repo list with per-row name / branch / unread badge."""

from __future__ import annotations

import logging
import math
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
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QPainter, QPen
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
from src.core.hook_server import (
    EVENT_NOTIFICATION,
    EVENT_STOP,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore


log = logging.getLogger(__name__)


# Hook events that drive per-row Claude-state transitions in
# RepoListModel.apply_hook_event. Other events (e.g. RepoAdded) are handled
# at the MainWindow level since they don't mutate per-row state.
_CLAUDE_STATE_EVENTS = frozenset(
    {EVENT_USER_PROMPT_SUBMIT, EVENT_STOP, EVENT_NOTIFICATION}
)


# Custom roles. Two orthogonal axes feed the row paint:
#   • Claude-driven alerts: ROLE_STATUS ("" / "done" / "attention") and
#     ROLE_WORKING. These ride the right-edge badge column.
#   • User-navigation cue: ROLE_LAST_FOCUSED. Boolean. Paints as a thin
#     left-edge stripe so it can't compete with the alert column.
# These two axes have completely separate storage and mutation paths in
# RepoListModel — a Claude event must never clobber the user's bookmark,
# and a user navigation must never clobber a Claude alert.
ROLE_REPO         = Qt.UserRole + 1
ROLE_BRANCH       = Qt.UserRole + 2
ROLE_STATUS       = Qt.UserRole + 3
ROLE_WORKING      = Qt.UserRole + 4   # bool — Claude mid-turn in this repo
ROLE_HAS_TERMINAL = Qt.UserRole + 5   # bool — a TerminalHost exists for this repo this session
ROLE_LAST_FOCUSED = Qt.UserRole + 6   # bool — user's previous selection (bookmark)


@dataclass(frozen=True)
class StatusDefinition:
    """Single source of truth for a Claude alert: tooltip label + badge paint."""
    value: str
    label: str
    color: QColor
    glyph: str


# Solarized-ish palette: red = needs attention (urgent), green = done (calmer).
STATUS_DONE_DEF = StatusDefinition(
    value="done",
    label="Claude finished a turn",
    color=QColor(133, 153, 0),
    glyph="✓",
)
STATUS_ATTENTION_DEF = StatusDefinition(
    value="attention",
    label="Claude needs input",
    color=QColor(220, 50, 47),
    glyph="!",
)

_ALL_STATUSES = (STATUS_DONE_DEF, STATUS_ATTENTION_DEF)

STATUS_DONE      = STATUS_DONE_DEF.value
STATUS_ATTENTION = STATUS_ATTENTION_DEF.value

STATUS_LABELS = {s.value: s.label for s in _ALL_STATUSES}
WORKING_LABEL = "Claude is working…"
LAST_FOCUSED_LABEL = "Last focused"


def _norm(path: str) -> str:
    """Canonicalize a path so set-membership checks agree no matter how the
    path was supplied (trailing slash, symlink, relative segment).

    Used as the single key shape for `_working`. Without this, a hook that
    reports `/symlink/repo` while the sidebar holds `/real/repo` would
    silently fail to flip the spinner on — the bug we hit while clicking
    off a working repo.
    """
    return os.path.realpath(path) if path else ""


def _format_elapsed(seconds: float) -> str:
    """Human "Ns / Nm Ms / Nh Mm" elapsed-time format.

    Bare seconds under a minute; `1m 23s` up to an hour; `1h 5m` thereafter
    (seconds dropped in the hours bucket — at multi-hour scale the digit
    isn't useful and would jitter the tooltip on every re-show).
    """
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    h, rem = divmod(s, 3600)
    return f"{h}h {rem // 60}m"

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
# Animation timing now lives in Settings.ui.animation — read from the
# instance, not at module level, so the TOML config controls these. See
# docstrings on AnimationSettings (src/core/settings.py) for the rationale
# behind the bubble-walk cadence and the sidebar-quiet-window proxy.


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

    # Emitted on the True↔False edge of any repo's working flag — coarser
    # than dataChanged(ROLE_WORKING), which fires per-row including
    # duplicate broadcasts. The window-title counter listens here so it
    # doesn't have to re-scan _working on every row repaint.
    working_changed = Signal()

    def __init__(self, store: RepoStore, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._branches: dict[str, str | None] = {}
        # Claude alerts only. Values: "", STATUS_DONE, STATUS_ATTENTION.
        # User-navigation state lives in _last_focused below, with its own role.
        self._status: dict[str, str] = {}
        self._working: set[str] = set()
        # Repo ids whose TerminalHost has been spawned in the current ccwork
        # session. Drives the visual difference between "touched" rows (bold
        # upright) and "untouched" rows (regular italic). Cleared on terminal
        # exit so a closed-then-not-reopened repo reverts to italic.
        self._active_ids: set[str] = set()
        # Per-repo timestamp of the last Claude-driven event
        # (Stop / Notification / UserPromptSubmit). Feeds the optional
        # auto-arrange sort. Setting _last_focused is user navigation, not
        # Claude activity, and does not stamp this dict.
        self._last_activity: dict[str, float] = {}
        # The previously-selected row path (normalized). Single value — only
        # one bookmark exists at a time. Mutated exclusively by set_last_focused;
        # no Claude event handler touches this field.
        self._last_focused: str | None = None
        # Per-path monotonic timestamp of the most recent UserPromptSubmit.
        # Set on UPS, cleared on Stop. Distinct from _last_activity (which
        # also stamps on Stop and Notification) — we need "turn began",
        # not "any Claude event happened". Path-keyed unnormalized to match
        # _status and _last_activity (not _working, which is normalized).
        self._turn_started: dict[str, float] = {}

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
        if role == ROLE_LAST_FOCUSED:
            return _norm(repo.path) == self._last_focused
        if role == Qt.ToolTipRole:
            # Prepend a human-readable status line so hovering a row tells
            # the user what the badge means without having to memorize the
            # color palette. Path stays as the second line for context.
            # Priority: working > Claude alert > last-focused bookmark.
            if _norm(repo.path) in self._working:
                started = self._turn_started.get(repo.path)
                if started is not None:
                    elapsed = _format_elapsed(time.monotonic() - started)
                    return f"{WORKING_LABEL}\n{repo.path}\nWorking {elapsed}"
                return f"{WORKING_LABEL}\n{repo.path}"
            label = STATUS_LABELS.get(self._status.get(repo.path, ""))
            if label:
                return f"{label}\n{repo.path}"
            if _norm(repo.path) == self._last_focused:
                return f"{LAST_FOCUSED_LABEL}\n{repo.path}"
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
        """Set the Claude-alert status for `path` ("done", "attention", or
        "" to clear). Stamps last_activity on DONE/ATTENTION so the
        auto-arrange sort reflects this event.

        Per-path state — every duplicate row for this path repaints together.
        User-navigation state (last-focused) lives in a separate field and
        is unaffected.
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

    def touch_activity(self, path: str) -> None:
        """Stamp `_last_activity[path]` without touching working/status state.

        Lets a UserPromptSubmit refresh the sort-recency key even when
        working was already True (the old code used a False→True toggle on
        set_working as a back-channel; this is the explicit version).
        """
        self._last_activity[path] = time.monotonic()

    def mark_turn_start(self, path: str) -> None:
        """Stamp the start of a Claude turn for tooltip elapsed-time display.

        Dict assignment overwrites on interrupt: a second UPS without an
        intervening Stop (Esc-interrupted turn, crashed turn) correctly
        restarts the elapsed counter from zero.
        """
        self._turn_started[path] = time.monotonic()

    def clear_turn_start(self, path: str) -> None:
        """Drop the turn-start timestamp on Stop. Idempotent."""
        self._turn_started.pop(path, None)

    def set_last_focused(self, path: str | None) -> None:
        """Set the user-navigation bookmark (or clear it with None).

        Independent of Claude alerts: setting this never clobbers a DONE /
        ATTENTION dot, and a Claude event never clobbers this. Paint
        composes the two via separate roles.
        """
        new_key = _norm(path) if path else None
        if new_key == self._last_focused:
            return
        old_key = self._last_focused
        self._last_focused = new_key
        # Repaint old row (stripe disappears) and new row (stripe appears).
        # Both lookups are by un-normalized path; we walk every row whose
        # _norm matches so duplicates share the bookmark state.
        for row in range(len(self._store.repos)):
            rp = self._store.repos[row].path
            n = _norm(rp)
            if n == old_key or n == new_key:
                idx = self.index(row)
                self.dataChanged.emit(idx, idx, [ROLE_LAST_FOCUSED, Qt.ToolTipRole])

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
        # Fire the title-counter signal only on the actual edge — the
        # `if working == was: return` guard above ensures we never emit on a
        # redundant set_working(path, True) when the path is already working.
        self.working_changed.emit()

    def any_working(self) -> bool:
        return bool(self._working)

    def working_paths(self) -> set[str]:
        """Normalized paths currently flagged as working. Read-only view."""
        return set(self._working)

    def is_working(self, path: str) -> bool:
        return _norm(path) in self._working

    def apply_hook_event(self, event: str, path: str) -> None:
        """Atomic per-row state transition for one Claude hook event.

        Owns the entire event → state mapping; callers don't need to know
        the per-event mutator sequence. UI side-effects (spinner timer,
        reorder scheduling) are handled by the RepoSidebar wrapper.

          • UserPromptSubmit — clear prior alert, mark working, stamp
            recency. Self-heals: if a prior turn never got a Stop, the
            existing working=True state is preserved (set_working no-ops)
            and touch_activity refreshes the timestamp anyway.
          • Stop — clear working, set DONE. Stamping is implicit in
            set_status for DONE/ATTENTION.
          • Notification — set ATTENTION. Does NOT clear working: a
            permission_prompt fires mid-turn and the turn is still live.
        """
        if event == EVENT_USER_PROMPT_SUBMIT:
            self.clear_status(path)
            self.set_working(path, True)
            self.touch_activity(path)
            self.mark_turn_start(path)
        elif event == EVENT_STOP:
            self.set_working(path, False)
            self.set_status(path, STATUS_DONE)
            self.clear_turn_start(path)
        elif event == EVENT_NOTIFICATION:
            self.set_status(path, STATUS_ATTENTION)

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
        return self._last_activity.get(path, 0.0)

    def apply_auto_arrange(self) -> bool:
        """Reorder _store.repos by Claude-activity recency desc.

        Repos with no recorded activity sort to the bottom in their
        current relative order (stable). Returns True if the order
        changed. Selection survives via persistent indices.
        """
        def sort_key(item):
            i, r = item
            ts = self._last_activity.get(r.path, 0.0)
            return (-ts if ts > 0 else float("inf"), i)
        return self._reorder_by(sort_key)

    def apply_terminal_grouping(self) -> bool:
        """Float repos with a live terminal to the top of the list.

        Stable within each group: relative order is preserved, so this
        composes cleanly after apply_auto_arrange.
        """
        active = self._active_ids

        def sort_key(item):
            i, r = item
            return (0 if r.id in active else 1, i)
        return self._reorder_by(sort_key)

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
            def k_act(item):
                i, r = item
                ts = self._last_activity.get(r.path, 0.0)
                return (-ts if ts > 0 else float("inf"), i)
            indexed = list(enumerate(repos))
            indexed.sort(key=k_act)
            repos = [r for _, r in indexed]
        if group_active:
            active = self._active_ids
            def k_grp(item):
                i, r = item
                return (0 if r.id in active else 1, i)
            indexed = list(enumerate(repos))
            indexed.sort(key=k_grp)
            repos = [r for _, r in indexed]
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

        # Per-path state stays only while at least one row still uses the
        # path — drop it once the last duplicate is gone.
        if not self._store.repos_for_path(path):
            self._branches.pop(path, None)
            self._status.pop(path, None)
            self._working.discard(_norm(path))
            self._last_activity.pop(path, None)
            self._turn_started.pop(path, None)
            if self._last_focused == _norm(path):
                self._last_focused = None
        self._store.save()
        return True


class RepoDelegate(QStyledItemDelegate):
    """Two-line row: name (bold) + branch (subtitle), unread badge right-aligned.

    All numeric layout knobs (row_height, padding_x, group_gap_h, glyph_w,
    glyph_gap, active_stripe_w, last_focused_stripe_w) come from
    `settings.ui.layout` — assigned as instance attributes by __init__ so
    they're read consistently as `self.ROW_HEIGHT` etc. The legacy uppercase
    names are kept to minimize delta in the paint code.
    """

    # The right-edge badge column is reserved for genuine Claude alerts
    # (working / done / attention). The last-focused bookmark paints a
    # left-edge stripe in a different code path and is NOT in these dicts.
    STATUS_COLORS = {s.value: s.color for s in _ALL_STATUSES}
    STATUS_GLYPHS = {s.value: s.glyph for s in _ALL_STATUSES}
    # Muted blue for the working spinner — distinct from the red/green
    # status dots so glance-state is unambiguous.
    SPINNER_COLOR = QColor(38, 139, 210)  # solarized blue

    # Base hue for the "last focused" left-edge stripe (solarized violet).
    # Modulated per-theme by _last_focused_stripe_color so it stays subtle.
    LAST_FOCUSED_BASE = QColor(108, 113, 196)

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

        # Last-focused bookmark: thin left-edge stripe instead of a right-edge
        # dot, so the badge column stays reserved for genuine Claude alerts.
        # Skip when the row is selected — the active stripe owns that edge.
        if not selected and last_focused:
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

        # Right-edge glyph: attention dot wins over the spinner so a
        # permission_prompt is glanceable even with desktop notifications
        # off; otherwise the braille spinner runs while Claude is working;
        # otherwise the color-coded status dot. STATUS_DONE never coincides
        # with working (Stop clears working before setting done).
        if working and status != STATUS_ATTENTION:
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
    # Emitted after the user picks "Copy path" — carries the path that just
    # landed on the clipboard so MainWindow can flash a status-bar
    # confirmation. The sidebar doesn't own a status bar; this keeps it
    # display-agnostic.
    path_copied = Signal(str)

    def __init__(self, store: RepoStore, parent=None, settings=None) -> None:
        super().__init__(parent)
        self._store = store
        self._settings = settings
        # Resolve animation knobs once; fall back to defaults when called
        # without settings (some test paths do this).
        from src.core.settings import AnimationSettings
        self._anim = (
            settings.ui.animation if settings is not None
            else AnimationSettings()
        )
        self._model = RepoListModel(store, self)

        self._view = QListView(self)
        self._view.setModel(self._model)
        layout_cfg = settings.ui.layout if settings is not None else None
        self._delegate = RepoDelegate(self._view, layout=layout_cfg)
        self._view.setItemDelegate(self._delegate)

        # Braille-spinner ticker. Only runs while at least one repo is in
        # the "working" state — otherwise it would repaint the viewport 10×
        # per second for no reason.
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(self._anim.spinner_interval_ms)
        self._spinner_timer.timeout.connect(self._advance_spinner)
        # Debounced auto-arrange. Restarted on every Claude-driven event
        # while ui.auto_arrange_repos is True; fires once after the
        # configured reorder_debounce_ms of quiet to avoid reshuffling
        # under the user's eye.
        self._reorder_timer = QTimer(self)
        self._reorder_timer.setSingleShot(True)
        self._reorder_timer.setInterval(self._anim.reorder_debounce_ms)
        self._reorder_timer.timeout.connect(self._apply_auto_arrange)
        # Quiet-window gate for the bubble walk. The walk fires only when
        # the sidebar has had no input (mouse, key, selection) for
        # the configured sidebar_quiet_ms. While the user is hovering, scrolling, or
        # picking a repo, _bump_activity() pushes the timestamp forward
        # and pending walks keep deferring; while they're typing in
        # xterm, no Qt events reach the sidebar so the timestamp
        # naturally ages and queued walks fire. _check_pending_walk
        # re-runs itself on _arrange_check_timer until the quiet
        # condition is met or the pending state is cleared.
        # Initial 0.0 lets the very first trigger fire immediately —
        # there's no genuine sidebar activity at startup.
        self._last_sidebar_activity = 0.0
        self._arrange_pending = False
        self._arrange_check_timer = QTimer(self)
        self._arrange_check_timer.setSingleShot(True)
        self._arrange_check_timer.timeout.connect(self._check_pending_walk)
        # Stepwise bubble-up: each tick swaps one adjacent pair toward the
        # composed target order (auto-arrange ⊕ grouping, whichever prefs
        # are on). Self-correcting — if a new active repo or a fresh
        # activity event arrives mid-animation, the next tick sees the
        # updated target and keeps walking. Stops when current == target.
        # Per-tick interval is recomputed by _step_arrange along a sine
        # ease-in-out curve, so the constructor default is a placeholder.
        self._arrange_step_timer = QTimer(self)
        self._arrange_step_timer.setInterval(self._anim.arrange_step_max_ms)
        self._arrange_step_timer.timeout.connect(self._step_arrange)
        # Resets at every walk start. Drives the easing curve.
        self._arrange_steps_taken = 0
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
        focus gate (_terminal_focused) defers until the user has actually
        engaged with a terminal; until then this just queues via
        _maybe_walk(). Same applies on terminal close.
        """
        self._model.set_terminal_active(repo_id, active)
        if self._settings is not None and getattr(
            self._settings.ui, "group_active_repos", False
        ):
            self._maybe_walk()
        # Boundary may have shifted (or the bold/italic font flipped) —
        # re-query sizeHints. No reorder yet.
        self._view.scheduleDelayedItemsLayout()

    def _bump_activity(self) -> None:
        """Mark the sidebar as just-touched. Pushes the quiet-window
        deadline forward so any pending walk keeps deferring."""
        self._last_sidebar_activity = time.monotonic()

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
            self._bump_activity()
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
            self._maybe_schedule_reorder()

    def apply_hook_event(self, event: str, path: str) -> None:
        """Single entry point for a Claude hook event affecting one path.

        Delegates state mutation to the model and refreshes UI side-effects
        (spinner timer + auto-arrange schedule). MainWindow._on_hook_event
        is a thin dispatcher over this method.
        """
        if event not in _CLAUDE_STATE_EVENTS:
            return
        self._model.apply_hook_event(event, path)
        self._refresh_spinner_timer()
        self._maybe_schedule_reorder()

    def _refresh_spinner_timer(self) -> None:
        """Start the spinner ticker when any row is working; stop otherwise."""
        if self._model.any_working():
            if not self._spinner_timer.isActive():
                self._spinner_timer.start()
        else:
            self._spinner_timer.stop()

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
        self._maybe_walk()

    def _maybe_walk(self) -> None:
        """Start the bubble walk if the sidebar is quiet; else defer.

        Single chokepoint for both auto-arrange and terminal-grouping
        triggers. The defer-and-recheck loop ensures the walk only runs
        when the user has been clearly off the sidebar for a moment —
        typically while typing in their terminal.
        """
        self._arrange_pending = True
        self._check_pending_walk()

    def _check_pending_walk(self) -> None:
        """Try to fire a pending walk. If the sidebar isn't quiet yet,
        re-arm the timer for when the quiet window would next elapse.
        """
        if not self._arrange_pending:
            return
        elapsed_ms = (time.monotonic() - self._last_sidebar_activity) * 1000
        if elapsed_ms >= self._anim.sidebar_quiet_ms:
            self._arrange_pending = False
            self._start_arrange_animation()
            return
        # Re-check exactly when the quiet window would close, plus a
        # small buffer so timer jitter can't undershoot.
        self._arrange_check_timer.start(int(self._anim.sidebar_quiet_ms - elapsed_ms) + 10)

    def _start_arrange_animation(self) -> None:
        """Walk one row toward the target order now, then keep ticking on
        the timer. No-op if already at target. Idempotent — if the timer
        is already running, it just keeps going (and naturally absorbs any
        new target, since each tick recomputes).
        """
        if self._arrange_step_timer.isActive():
            return
        # New walk — reset the step counter so the easing curve restarts
        # from the slow-start endpoint.
        self._arrange_steps_taken = 0
        # Step once now so the user sees motion immediately, not after a
        # 220 ms gap (the eye reads "trigger → motion" as causal).
        if self._step_arrange():
            self._arrange_step_timer.start()

    def _step_arrange(self) -> bool:
        """Advance one adjacent swap toward the composed target. Returns
        True if more work remains; False once converged (and stops timer).
        """
        if self._settings is None:
            self._arrange_step_timer.stop()
            return False
        target = self._model.target_order_ids(
            auto_arrange=bool(getattr(self._settings.ui, "auto_arrange_repos", False)),
            group_active=bool(getattr(self._settings.ui, "group_active_repos", False)),
        )
        current = [
            self._model.repo_at(i).id for i in range(self._model.rowCount())
        ]
        if current == target:
            self._arrange_step_timer.stop()
            return False
        for i, (cur_id, tgt_id) in enumerate(zip(current, target)):
            if cur_id == tgt_id:
                continue
            # The id that *should* sit at row i is currently lower; bubble
            # it up by one. Topmost mismatch wins so rows settle from the
            # top down — visually, the highest-priority repo finishes
            # first, then the next, etc.
            src_row = current.index(tgt_id)
            self._model.move_row_up(src_row)
            self._arrange_steps_taken += 1
            self._arrange_step_timer.setInterval(self._next_step_interval(target))
            return True
        self._arrange_step_timer.stop()
        return False

    def _next_step_interval(self, target: list[str]) -> int:
        """Sine ease-in-out cadence between swaps.

        After each swap we estimate total = swaps_done + remaining_swaps,
        then map the gap-to-next-swap onto sin(pi · x). x = 0 (first gap)
        and x = 1 (last gap) both give MAX (slow); x = 0.5 gives MIN
        (fast middle). The estimate floats — if a new active repo arrives
        mid-walk, total grows and the curve smoothly extends rather than
        snapping to a new ramp.
        """
        remaining = self._simulate_remaining_swaps(target)
        total = self._arrange_steps_taken + remaining
        max_ms = self._anim.arrange_step_max_ms
        min_ms = self._anim.arrange_step_min_ms
        if total <= 2:
            # 1 or 2 swaps total: too few for a meaningful curve. Slow &
            # deliberate reads better than abrupt.
            return max_ms
        gap_index = self._arrange_steps_taken - 1  # gap that follows this swap
        last_gap_index = total - 2
        # Clamp at 1.0: on the converging swap, gap_index can momentarily
        # exceed last_gap_index (the timer is about to be stopped anyway).
        x = min(1.0, gap_index / last_gap_index)
        eased = math.sin(math.pi * x)  # 0 at endpoints, 1 in middle
        # round (not int) to absorb sin(π) ≈ 1.22e-16 float drift at the
        # x=1.0 endpoint — int() would truncate to MAX-1 instead of MAX.
        return round(
            max_ms - (max_ms - min_ms) * eased
        )

    def _simulate_remaining_swaps(self, target: list[str]) -> int:
        """Replay the bubble-up algorithm on a copy of the current order
        and count swaps until convergence. A simple mismatch count over-
        estimates: when one id bubbles past several others, every row in
        between is "wrong" right now but resolves implicitly. The sim
        gives the exact number of move_row_up calls remaining.
        """
        current = [
            self._model.repo_at(j).id for j in range(self._model.rowCount())
        ]
        swaps = 0
        while current != target:
            for i, (c, t) in enumerate(zip(current, target)):
                if c == t:
                    continue
                src = current.index(t)
                current[src - 1], current[src] = current[src], current[src - 1]
                swaps += 1
                break
            else:
                break  # nothing to swap (shouldn't happen if current != target)
        return swaps

    def _advance_spinner(self) -> None:
        self._delegate.spinner_frame += 1
        # Repaint only rows that are currently working.
        for row in range(self._model.rowCount()):
            idx = self._model.index(row)
            if idx.data(ROLE_WORKING):
                self._view.update(idx)

    # ── signals ──

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        # Selection change is a strong "user is on the sidebar" signal —
        # arguably stronger than mouse hover. Push the quiet deadline.
        self._bump_activity()
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
        self._add_path(path)

    def _add_path(self, path: str) -> Repo:
        """Append a row for `path`, select it, emit repo_added. Returns the new Repo."""
        added = self._model.add_repo(path)
        # Select the just-added row by id (path may be ambiguous now that
        # duplicates are allowed).
        row = self._model.index_of_id(added.id)
        if row >= 0:
            self._view.setCurrentIndex(self._model.index(row))
        self.repo_added.emit(added)
        return added

    def _on_context_menu(self, pos: QPoint) -> None:
        self._bump_activity()
        idx = self._view.indexAt(pos)
        if not idx.isValid():
            return
        repo = self._model.repo_at(idx.row())
        if repo is None:
            return
        menu = self._build_context_menu(repo, idx.row())
        menu.exec(self._view.viewport().mapToGlobal(pos))

    def _build_context_menu(self, repo: Repo, row: int) -> QMenu:
        """Construct the row right-click menu. Split out from
        ``_on_context_menu`` so tests can inspect actions (enabled state,
        tooltips, ordering) without simulating an actual right-click."""
        menu = QMenu(self)

        reload_act = QAction("Reload terminal", menu)
        reload_act.setToolTip("Respawn xterm to pick up new settings. Loses in-flight shell state.")
        reload_act.triggered.connect(lambda _=False, r=repo: self._confirm_reload(r))
        menu.addAction(reload_act)

        clone_act = QAction("Clone this repo", menu)
        clone_act.setToolTip("Add a second sidebar row pointing at the same directory (parallel session).")
        clone_act.triggered.connect(lambda _=False, r=repo: self._add_path(r.path))
        menu.addAction(clone_act)

        # Path-action group: no separator before, to read as one "things you
        # can do with this path" cluster alongside Clone. The existing
        # separator below fences off the cosmetic badge items.
        open_fm_act = QAction("Open in file manager", menu)
        if shutil.which("xdg-open") is None:
            open_fm_act.setEnabled(False)
            open_fm_act.setToolTip(
                "xdg-open not found. Install the xdg-utils package."
            )
        else:
            open_fm_act.setToolTip(
                "Launches your desktop's default file manager at the repo directory."
            )
            open_fm_act.triggered.connect(
                lambda _=False, r=repo: self._open_in_file_manager(r)
            )
        menu.addAction(open_fm_act)

        copy_path_act = QAction("Copy path", menu)
        copy_path_act.setToolTip("Copy the absolute repo path to the clipboard.")
        copy_path_act.triggered.connect(lambda _=False, r=repo: self._copy_path(r))
        menu.addAction(copy_path_act)

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
        remove_act.triggered.connect(lambda _=False, r=repo, row=row: self._confirm_remove(r, row))
        menu.addAction(remove_act)

        return menu

    def _open_in_file_manager(self, repo: Repo) -> None:
        """Spawn xdg-open at repo.path. The menu's enabled-state probe at
        build time guarantees xdg-open is on PATH when this is reachable."""
        ok = QProcess.startDetached("xdg-open", [repo.path])
        if not ok:
            log.warning("xdg-open failed to launch for %s", repo.path)

    def _copy_path(self, repo: Repo) -> None:
        """Put `repo.path` on the system clipboard and notify MainWindow
        so it can flash a status-bar confirmation."""
        QGuiApplication.clipboard().setText(repo.path)
        self.path_copied.emit(repo.path)

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
