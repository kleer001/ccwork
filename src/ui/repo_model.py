"""Qt list-model for the repo sidebar: per-row branch / status / activity state.

`RepoListModel` owns the Claude-event → per-row-state mapping
(`apply_hook_event`) plus the auto-arrange / terminal-grouping reorder
logic. The custom `ROLE_*` roles defined here are the model's data
vocabulary, consumed by `RepoDelegate` (painting) and `RepoSidebar`
(animation). Badge presentation constants live in `badge_theme`.
"""

from __future__ import annotations

import os
import time

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    Qt,
    Signal,
)

from src.core import repo_store
from src.core.hook_server import (
    EVENT_NOTIFICATION,
    EVENT_PRE_TOOL_USE,
    EVENT_SESSION_END,
    EVENT_SESSION_START,
    EVENT_STOP,
    EVENT_SUBAGENT_STOP,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore
from src.ui.badge_theme import (
    BG_AGENTS_LABEL,
    LAST_FOCUSED_LABEL,
    SESSION_ACTIVE_LABEL,
    STATUS_ATTENTION,
    STATUS_DONE,
    STATUS_LABELS,
    TERMINAL_ONLY_LABEL,
    WORKING_LABEL,
)


# Hook events that drive per-row Claude-state transitions in
# RepoListModel.apply_hook_event. Other events (e.g. RepoAdded) are handled
# at the MainWindow level since they don't mutate per-row state.
_CLAUDE_STATE_EVENTS = frozenset(
    {
        EVENT_USER_PROMPT_SUBMIT,
        EVENT_STOP,
        EVENT_NOTIFICATION,
        EVENT_PRE_TOOL_USE,
        EVENT_SUBAGENT_STOP,
        EVENT_SESSION_START,
        EVENT_SESSION_END,
    }
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
ROLE_PATH_MISSING = Qt.UserRole + 7   # bool — repo.path doesn't exist on disk (renamed/deleted)
ROLE_BG_AGENTS    = Qt.UserRole + 8   # int — background subagents currently running
ROLE_SESSION_ACTIVE = Qt.UserRole + 9 # bool — a live Claude session exists in this terminal


def _norm(path: str) -> str:
    """Canonicalize a path so set-membership checks agree no matter how the
    path was supplied (trailing slash, symlink, relative segment).

    Used as the single key shape for `_working`. Without this, a hook that
    reports `/symlink/repo` while the sidebar holds `/real/repo` would
    silently fail to flip the spinner on — the bug we hit while clicking
    off a working repo.
    """
    return os.path.realpath(path) if path else ""


def _is_background_task_dispatch(payload: dict | None) -> bool:
    """True iff `payload` describes a PreToolUse for a backgrounded Task.

    Claude Code's PreToolUse payload carries `tool_name` and `tool_input`.
    We register the hook with a "Task" matcher so the tool check is
    belt-and-braces; the `run_in_background` flag is what genuinely
    distinguishes the case we care about — foreground subagents block the
    turn and are already covered by the working spinner.
    """
    if not isinstance(payload, dict):
        return False
    if payload.get("tool_name") != "Task":
        return False
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return False
    return bool(tool_input.get("run_in_background"))


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
        # Parallel to _branches: True when repo.path is gone from disk
        # (rename / delete / unmounted FS). Distinguishes "(path missing)"
        # from "(detached)" in the branch sub-line — a detached HEAD also
        # makes current_branch() return None, so we can't tell them apart
        # from the branch cache alone. Populated by refresh_branches().
        self._path_missing: dict[str, bool] = {}
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
        # Per-path count of background subagents currently running.
        # Incremented on PreToolUse(tool=Task, run_in_background=True),
        # decremented on SubagentStop (clamped at 0). Path-keyed unnormalized
        # to match _status / _last_activity. Drives the BG_AGENT_FRAMES
        # twinkle when the main turn is idle but background work is still
        # in flight.
        self._bg_agents: dict[str, int] = {}
        # Per-path live-session flag. True between SessionStart and
        # SessionEnd. Drives the ambient terminal-state badge (⠿ when a
        # session is live, ▌ when only a bare bash terminal exists).
        # Path-keyed unnormalized to match the other Claude-state dicts.
        self._session_active: dict[str, bool] = {}

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
        if role == ROLE_PATH_MISSING:
            return self._path_missing.get(repo.path, False)
        if role == ROLE_STATUS:
            return self._status.get(repo.path, "")
        if role == ROLE_WORKING:
            return _norm(repo.path) in self._working
        if role == ROLE_HAS_TERMINAL:
            return repo.id in self._active_ids
        if role == ROLE_LAST_FOCUSED:
            return _norm(repo.path) == self._last_focused
        if role == ROLE_BG_AGENTS:
            return self._bg_agents.get(repo.path, 0)
        if role == ROLE_SESSION_ACTIVE:
            return self._session_active.get(repo.path, False)
        if role == Qt.ToolTipRole:
            # Prepend a human-readable status line so hovering a row tells
            # the user what the badge means without having to memorize the
            # color palette. Path stays as the second line for context.
            # Priority: working > Claude alert > background agents > last-focused.
            if _norm(repo.path) in self._working:
                started = self._turn_started.get(repo.path)
                if started is not None:
                    elapsed = _format_elapsed(time.monotonic() - started)
                    return f"{WORKING_LABEL}\n{repo.path}\nWorking {elapsed}"
                return f"{WORKING_LABEL}\n{repo.path}"
            label = STATUS_LABELS.get(self._status.get(repo.path, ""))
            if label:
                return f"{label}\n{repo.path}"
            bg = self._bg_agents.get(repo.path, 0)
            if bg > 0:
                noun = "agent" if bg == 1 else "agents"
                return f"{BG_AGENTS_LABEL}\n{repo.path}\n{bg} background {noun}"
            if _norm(repo.path) == self._last_focused:
                return f"{LAST_FOCUSED_LABEL}\n{repo.path}"
            # Ambient terminal-state tooltips: only meaningful when a row
            # has a live terminal. The delegate gates the matching glyph
            # paint on has_terminal too, so the two channels agree.
            has_terminal = repo.id in self._active_ids
            if has_terminal:
                if self._session_active.get(repo.path, False):
                    return f"{SESSION_ACTIVE_LABEL}\n{repo.path}"
                return f"{TERMINAL_ONLY_LABEL}\n{repo.path}"
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
        """Recompute branch subtitle + path-existence for every repo.

        Both axes share the same refresh cadence: a missing path implies
        current_branch() will fail, so we only pay one extra `isdir` syscall
        per repo on top of the git invocation that's already happening.
        Call on focus/refresh.
        """
        changed_roles: list[int] = []
        for r in self._store.repos:
            missing = not os.path.isdir(r.path)
            if self._path_missing.get(r.path, False) != missing:
                self._path_missing[r.path] = missing
                if ROLE_PATH_MISSING not in changed_roles:
                    changed_roles.append(ROLE_PATH_MISSING)
            new = repo_store.current_branch(r.path)
            if self._branches.get(r.path) != new:
                self._branches[r.path] = new
                if ROLE_BRANCH not in changed_roles:
                    changed_roles.append(ROLE_BRANCH)
        if changed_roles and self._store.repos:
            top = self.index(0)
            bot = self.index(len(self._store.repos) - 1)
            self.dataChanged.emit(top, bot, changed_roles)

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

    def bg_agents(self, path: str) -> int:
        return self._bg_agents.get(path, 0)

    def is_session_active(self, path: str) -> bool:
        return self._session_active.get(path, False)

    def _set_session_active(self, path: str, active: bool) -> None:
        """Flip the session-active flag and broadcast a repaint.

        On SessionEnd we also clear `_status`, `_working`, and `_bg_agents`
        for `path` — the session is over, so its per-session signals (the
        DONE/ATTENTION dot, a stuck working spinner, leftover background
        agents whose SubagentStop didn't arrive) are stale and would
        otherwise obscure the new "bare terminal" indicator.
        """
        old = self._session_active.get(path, False)
        roles: list[int] = []
        if old != active:
            self._session_active[path] = active
            roles.append(ROLE_SESSION_ACTIVE)
            roles.append(Qt.ToolTipRole)
        if not active:
            # Cascade-clear per-session signals. Doing it directly on the
            # dicts (not via the public mutators) keeps everything inside
            # one dataChanged emission below — set_working / set_status
            # would each fire their own.
            if _norm(path) in self._working:
                self._working.discard(_norm(path))
                roles.append(ROLE_WORKING)
                self.working_changed.emit()
            if self._status.pop(path, None) is not None:
                roles.append(ROLE_STATUS)
            if self._bg_agents.pop(path, None) is not None:
                roles.append(ROLE_BG_AGENTS)
            self._turn_started.pop(path, None)
        if roles:
            # Deduplicate while preserving order — repeated roles in the
            # list don't break anything but they're noise in the signal.
            seen: list[int] = []
            for r in roles:
                if r not in seen:
                    seen.append(r)
            self._emit_changed_for_path(path, seen)

    def _bump_bg_agents(self, path: str, delta: int) -> None:
        """Adjust the background-agent counter for `path` and repaint.

        Clamped at zero — a stray SubagentStop without a matching dispatch
        (out-of-order delivery, or a foreground subagent we didn't count)
        must not push the counter negative.
        """
        old = self._bg_agents.get(path, 0)
        new = max(0, old + delta)
        if new == old:
            return
        if new == 0:
            self._bg_agents.pop(path, None)
        else:
            self._bg_agents[path] = new
        self._emit_changed_for_path(path, [ROLE_BG_AGENTS, Qt.ToolTipRole])

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

    def any_bg_agents(self) -> bool:
        """True iff at least one repo has detached background subagents
        running. Used by the sidebar to keep the spinner timer ticking
        even when no main turn is in flight, so the twinkle animation
        on the bg-agent indicator stays alive."""
        return any(v > 0 for v in self._bg_agents.values())

    def working_paths(self) -> set[str]:
        """Normalized paths currently flagged as working. Read-only view."""
        return set(self._working)

    def is_working(self, path: str) -> bool:
        return _norm(path) in self._working

    def apply_hook_event(
        self, event: str, path: str, payload: dict | None = None
    ) -> None:
        """Atomic per-row state transition for one Claude hook event.

        Owns the entire event → state mapping; callers don't need to know
        the per-event mutator sequence. UI side-effects (spinner timer,
        reorder scheduling) are handled by the RepoSidebar wrapper.

          • UserPromptSubmit — clear prior alert, mark working, stamp
            recency. Self-heals: if a prior turn never got a Stop, the
            existing working=True state is preserved (set_working no-ops)
            and touch_activity refreshes the timestamp anyway.
          • Stop — clear working, set DONE. Stamping is implicit in
            set_status for DONE/ATTENTION. Does NOT clear _bg_agents:
            backgrounded subagents survive past the main turn end, which
            is the whole point of the ◌ indicator.
          • Notification — set ATTENTION. Does NOT clear working: a
            permission_prompt fires mid-turn and the turn is still live.
          • PreToolUse — increment _bg_agents iff the tool is "Task" and
            tool_input.run_in_background is True. Foreground Task calls
            block the turn, so the working spinner already covers them.
          • SubagentStop — decrement _bg_agents (clamped at 0). Fires for
            both foreground and background agents; the clamp absorbs the
            foreground decrements we never incremented for.
          • SessionStart — flip _session_active[path] = True. The badge
            column switches from ▌ (bare terminal) to ⠿ (Claude is here)
            once no higher-priority alert is masking either.
          • SessionEnd — flip _session_active[path] = False AND cascade-
            clear _status / _working / _bg_agents / _turn_started for
            this path. The session is over; those signals are stale and
            would otherwise mask the new ▌ ambient indicator.
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
        elif event == EVENT_PRE_TOOL_USE:
            if _is_background_task_dispatch(payload):
                self._bump_bg_agents(path, +1)
        elif event == EVENT_SUBAGENT_STOP:
            self._bump_bg_agents(path, -1)
        elif event == EVENT_SESSION_START:
            self._set_session_active(path, True)
        elif event == EVENT_SESSION_END:
            self._set_session_active(path, False)

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

    def rebind_repo(self, repo_id: str, new_path: str) -> None:
        """Repoint one row at `new_path`. The display name updates implicitly
        because `Repo.display_name` is derived from `path` basename + emoji +
        instance (see src/core/repo_store.py:Repo). Invalidates the branch
        and path-missing caches for both old and new paths and emits a
        single dataChanged covering name, branch, and missing-state.
        """
        repo = self._store.find_by_id(repo_id)
        if repo is None:
            return
        new_path = os.path.realpath(new_path)
        if os.path.realpath(repo.path) == new_path:
            return
        old_path = repo.path
        repo.path = new_path
        self._store.save()
        self._branches.pop(old_path, None)
        self._path_missing.pop(old_path, None)
        self._branches[new_path] = repo_store.current_branch(new_path)
        self._path_missing[new_path] = not os.path.isdir(new_path)
        row = self.index_of_id(repo_id)
        if row >= 0:
            idx = self.index(row)
            self.dataChanged.emit(
                idx, idx,
                [Qt.DisplayRole, Qt.ToolTipRole, ROLE_BRANCH, ROLE_PATH_MISSING],
            )

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
