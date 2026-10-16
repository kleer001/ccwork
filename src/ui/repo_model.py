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
from src.core.hook_server import remove_row_title, write_row_title
from src.core.hook_server import (
    EVENT_CLAUDE_EXITED,
    EVENT_NOTIFICATION,
    EVENT_PERMISSION_REQUEST,
    EVENT_POST_COMPACT,
    EVENT_PRE_COMPACT,
    EVENT_SESSION_END,
    EVENT_SESSION_START,
    EVENT_STOP,
    EVENT_STOP_FAILURE,
    EVENT_SUBAGENT_START,
    EVENT_SUBAGENT_STOP,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore
from src.ui.badge_theme import (
    CLAUDE_OPEN_TEXT,
    COMPACTING_LABEL,
    ERROR_WORDS,
    LAST_FOCUSED_LABEL,
    SESSION_ACTIVE_LABEL,
    STATUS_ANSWER,
    STATUS_ATTENTION,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_LABELS,
    STATUS_USAGE_LIMIT,
    SUBAGENTS_LABEL,
    TERMINAL_ONLY_LABEL,
    USAGE_LIMIT_WORDS,
    WORKING_LABEL,
    WORKING_TEXT,
)


# Hook events that drive per-row Claude-state transitions in
# RepoListModel.apply_hook_event. Other events (e.g. RepoAdded) are handled
# at the MainWindow level since they don't mutate per-row state.
_CLAUDE_STATE_EVENTS = frozenset(
    {
        EVENT_USER_PROMPT_SUBMIT,
        EVENT_STOP,
        EVENT_STOP_FAILURE,
        EVENT_NOTIFICATION,
        EVENT_PERMISSION_REQUEST,
        EVENT_SUBAGENT_START,
        EVENT_SUBAGENT_STOP,
        EVENT_PRE_COMPACT,
        EVENT_POST_COMPACT,
        EVENT_SESSION_START,
        EVENT_SESSION_END,
        EVENT_CLAUDE_EXITED,
    }
)

# Notification types that set a badge, and the types that clear one.
# Every other notification_type (idle_prompt, auth_success, …) is ignored.
_PERMISSION_NOTIFICATIONS = frozenset({"permission_prompt"})
_ANSWER_NOTIFICATIONS = frozenset({"elicitation_dialog", "elicitation_url_dialog"})
_ANSWERED_NOTIFICATIONS = frozenset({"elicitation_complete", "elicitation_response"})
_RESUMED_NOTIFICATIONS = frozenset({"quota_auto_resume_fired"})


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
ROLE_SUBAGENTS    = Qt.UserRole + 8   # int — subagents (fg or bg) currently running
ROLE_SESSION_ACTIVE = Qt.UserRole + 9 # bool — a live Claude session exists in this terminal
ROLE_ACTIVE_GROUP = Qt.UserRole + 10  # bool — row belongs to the floated "in progress" group
ROLE_COMPACTING   = Qt.UserRole + 11  # bool — Claude is compacting its context
ROLE_STATUS_WORD  = Qt.UserRole + 12  # str — the badge's word ("Rate limited", …), "" with no badge
ROLE_TITLE        = Qt.UserRole + 13  # str — the row's editable title, "" when unset
ROLE_STATUS_TEXT  = Qt.UserRole + 14  # str — line-3 status text ("Working · 2m", …)


def _norm(path: str) -> str:
    """Canonicalize a path so set-membership checks agree no matter how the
    path was supplied (trailing slash, symlink, relative segment).

    Used as the key shape for the `_last_focused` bookmark.
    """
    return os.path.realpath(path) if path else ""


def _tool_summary(payload: dict) -> str:
    """One-line "Tool: detail" for a PermissionRequest payload, e.g.
    "Bash: rm -rf build". The detail is the first string field of
    `tool_input` that names what the tool acts on."""
    name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    if not name or not isinstance(tool_input, dict):
        return name
    for key in ("command", "file_path", "path", "url", "pattern", "description"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return f"{name}: {value.splitlines()[0][:80]}"
    return name


def _format_minutes(seconds: float) -> str:
    """Coarse elapsed time for the row's status line: "40s", "2m", "1h 5m".
    Minute steps keep the line still while the spinner animates."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    h, rem = divmod(s, 3600)
    return f"{h}h {rem // 60}m"


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
        # Claude state below is keyed by repo id: each hook event carries the
        # row id of the terminal that sent it, so duplicate rows on one path
        # keep independent state.
        # Claude alerts only. Values: "" or a STATUS_RANK key.
        # User-navigation state lives in _last_focused below, with its own role.
        self._status: dict[str, str] = {}
        # The specific word for the current status (e.g. "Rate limited" for
        # an error). Absent → the status label from badge_theme.
        self._status_word: dict[str, str] = {}
        # Rows whose session is compacting its context (PreCompact →
        # PostCompact / Stop / next prompt).
        self._compacting: set[str] = set()
        # "Tool: summary" of the call waiting for approval, from
        # PermissionRequest. Cleared with the permission badge.
        self._pending_tool: dict[str, str] = {}
        # Last title the row and its Claude session agreed on, per row. A
        # row title that differs from it was changed on the ccwork side
        # and is pushed to Claude; see sync_session_title.
        self._title_synced: dict[str, str] = {}
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
        # Per-row monotonic timestamp of the most recent UserPromptSubmit.
        # Set on UPS, cleared on Stop. Distinct from _last_activity (which
        # also stamps on Stop and Notification) — we need "turn began",
        # not "any Claude event happened".
        self._turn_started: dict[str, float] = {}
        # Per-row set of live subagent ids (foreground or background).
        # SubagentStart adds its `agent_id`, SubagentStop removes the same
        # id; a resumed subagent fires SubagentStart again and the set
        # absorbs the repeat. Drives the SUBAGENT_FRAMES twinkle —
        # painted in the inboard right-edge slot while a subagent is in
        # flight, independent of the main turn's working state (whose glyph
        # sits in the outboard slot). The two indicators occupy separate
        # slots so the user can tell at a glance that Claude has dispatched
        # parallel work.
        self._subagents: dict[str, set[str]] = {}
        # Per-row live-session flag. True between SessionStart and
        # SessionEnd. Drives the ambient ⠿ badge and membership in the
        # active group (a bare bash terminal is neither).
        self._session_active: dict[str, bool] = {}
        # Per-row set of live Claude session ids (between SessionStart and
        # SessionEnd). A nested `claude` can run inside the row's terminal,
        # so we only run the per-session teardown cascade (clear working /
        # status / subagents) when the LAST session in the terminal ends.
        self._live_sessions: dict[str, set[str]] = {}
        # Per-row monotonic stamp of the moment the last Claude session in
        # the row's terminal ended. Sinks the row past every other repo on the sort
        # axis: a finished session isn't pending work, and a row left sitting
        # near the top reads as unfinished business. Cleared by the next
        # activity on the row (and by a fresh SessionStart).
        self._session_ended: dict[str, float] = {}

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
            return self._status.get(repo.id, "")
        if role == ROLE_WORKING:
            return repo.id in self._working
        if role == ROLE_HAS_TERMINAL:
            return repo.id in self._active_ids
        if role == ROLE_LAST_FOCUSED:
            return _norm(repo.path) == self._last_focused
        if role == ROLE_SUBAGENTS:
            return len(self._subagents.get(repo.id, ()))
        if role == ROLE_COMPACTING:
            return repo.id in self._compacting
        if role == ROLE_STATUS_WORD:
            return self.status_word(repo.id)
        if role == ROLE_TITLE:
            return repo.title
        if role == ROLE_STATUS_TEXT:
            return self._status_text(repo)
        if role == ROLE_SESSION_ACTIVE:
            return self._session_active.get(repo.id, False)
        if role == ROLE_ACTIVE_GROUP:
            return self._in_active_group(repo)
        if role == Qt.ToolTipRole:
            # Prepend a human-readable status line so hovering a row tells
            # the user what the badge means without having to memorize the
            # color palette. Path stays as the second line for context.
            # Priority: working > Claude alert > subagents > last-focused.
            if repo.id in self._working:
                started = self._turn_started.get(repo.id)
                if started is not None:
                    elapsed = _format_elapsed(time.monotonic() - started)
                    return f"{WORKING_LABEL}\n{repo.path}\nWorking {elapsed}"
                return f"{WORKING_LABEL}\n{repo.path}"
            label = self.status_word(repo.id)
            if label:
                tool = self._pending_tool.get(repo.id)
                if tool and self._status.get(repo.id) == STATUS_ATTENTION:
                    return f"{label}\n{repo.path}\n{tool}"
                return f"{label}\n{repo.path}"
            if repo.id in self._compacting:
                return f"{COMPACTING_LABEL}\n{repo.path}"
            sub = len(self._subagents.get(repo.id, ()))
            if sub > 0:
                noun = "subagent" if sub == 1 else "subagents"
                return f"{SUBAGENTS_LABEL}\n{repo.path}\n{sub} {noun}"
            if _norm(repo.path) == self._last_focused:
                return f"{LAST_FOCUSED_LABEL}\n{repo.path}"
            # Ambient terminal-state tooltips: only meaningful when a row
            # has a live terminal. The delegate gates the matching glyph
            # paint on has_terminal too, so the two channels agree.
            has_terminal = repo.id in self._active_ids
            if has_terminal:
                if self._session_active.get(repo.id, False):
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

    def _emit_changed_for_id(self, repo_id: str, roles: list[int]) -> None:
        """dataChanged for the one row with `repo_id`."""
        row = self.index_of_id(repo_id)
        if row >= 0:
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

    def set_status(self, repo_id: str, status: str, word: str = "") -> None:
        """Set the Claude-alert status for one row (a STATUS_RANK key, or ""
        to clear). `word` overrides the status label for this badge (e.g.
        "Rate limited" for an error). Any badge stamps last_activity so the
        auto-arrange sort reflects this event. Leaving the permission badge
        also drops the pending-tool text.

        User-navigation state (last-focused) lives in a separate field and
        is unaffected.
        """
        if status:
            self._status[repo_id] = status
            self._stamp_activity(repo_id)
        else:
            self._status.pop(repo_id, None)
        if word:
            self._status_word[repo_id] = word
        else:
            self._status_word.pop(repo_id, None)
        if status != STATUS_ATTENTION:
            self._pending_tool.pop(repo_id, None)
        self._emit_changed_for_id(
            repo_id, [ROLE_STATUS, ROLE_STATUS_WORD, Qt.ToolTipRole],
        )

    def status_word(self, repo_id: str) -> str:
        """The badge's word for one row, or "" when no badge shows."""
        status = self._status.get(repo_id, "")
        if not status:
            return ""
        return self._status_word.get(repo_id) or STATUS_LABELS[status]

    def _status_text(self, repo: Repo) -> str:
        """Line-3 text: the badge word, else the live state, else ""."""
        word = self.status_word(repo.id)
        if word:
            return word
        if repo.id in self._compacting:
            return COMPACTING_LABEL
        if repo.id in self._working:
            started = self._turn_started.get(repo.id)
            if started is None:
                return WORKING_TEXT
            return f"{WORKING_TEXT} · {_format_minutes(time.monotonic() - started)}"
        if repo.id in self._active_ids and self._session_active.get(repo.id, False):
            return CLAUDE_OPEN_TEXT
        return ""

    def set_title(self, repo_id: str, title: str) -> None:
        """Set or clear (`""`) one row's title from the ccwork side — the
        sidebar menu or `ccwork-rename`. Leaves the synced title alone, so
        the hook sink pushes the new title to Claude at the next prompt."""
        repo = self._store.find_by_id(repo_id)
        title = " ".join(title.split())
        if repo is None or repo.title == title:
            return
        self._title_synced.setdefault(repo_id, repo.title)
        repo.title = title
        self._store.save()
        self._publish_title(repo)
        self._emit_changed_for_id(repo_id, [ROLE_TITLE])

    def sync_session_title(self, repo_id: str, session_title: str | None) -> None:
        """Reconcile the row title with the session's custom title, as seen
        in a SessionStart / UserPromptSubmit payload.

        A session title that differs from a row title still in sync was
        renamed on the Claude side (`/rename`), so the row adopts it.
        Otherwise the sink has just pushed the row title to Claude, and the
        two now agree. A missing session title never clears the row title.
        """
        repo = self._store.find_by_id(repo_id)
        if repo is None:
            return
        synced = self._title_synced.get(repo_id, repo.title)
        if session_title and session_title != repo.title and repo.title == synced:
            repo.title = " ".join(session_title.split())
            self._store.save()
            self._emit_changed_for_id(repo_id, [ROLE_TITLE])
        self._title_synced[repo_id] = repo.title
        self._publish_title(repo)

    def publish_titles(self) -> None:
        """Write every row's title file — at startup, before any hook runs."""
        for repo in self._store.repos:
            self._publish_title(repo)

    def _publish_title(self, repo: Repo) -> None:
        write_row_title(repo.id, repo.title, self._title_synced.get(repo.id, repo.title))

    def _clear_status_if(self, repo_id: str, status: str) -> None:
        """Clear the badge only while it is `status` — an end event for one
        badge must not wipe a different one."""
        if self._status.get(repo_id) == status:
            self.clear_status(repo_id)

    def set_compacting(self, repo_id: str, compacting: bool) -> None:
        was = repo_id in self._compacting
        if compacting == was:
            return
        if compacting:
            self._compacting.add(repo_id)
        else:
            self._compacting.discard(repo_id)
        self._emit_changed_for_id(repo_id, [ROLE_COMPACTING, Qt.ToolTipRole])

    def is_compacting(self, repo_id: str) -> bool:
        return repo_id in self._compacting

    def clear_status(self, repo_id: str) -> None:
        self.set_status(repo_id, "")

    def touch_activity(self, repo_id: str) -> None:
        """Stamp `_last_activity[repo_id]` without touching working/status state.

        Lets a UserPromptSubmit refresh the sort-recency key even when
        working was already True (the old code used a False→True toggle on
        set_working as a back-channel; this is the explicit version).
        """
        self._stamp_activity(repo_id)

    def _stamp_activity(self, repo_id: str) -> None:
        """Record "something Claude-driven just happened here".

        Also lifts any session-ended sink stamp — the row is live again,
        so it belongs back on the recency axis rather than at the bottom.
        """
        self._last_activity[repo_id] = time.monotonic()
        self._session_ended.pop(repo_id, None)

    def mark_turn_start(self, repo_id: str) -> None:
        """Stamp the start of a Claude turn for tooltip elapsed-time display.

        Dict assignment overwrites on interrupt: a second UPS without an
        intervening Stop (Esc-interrupted turn, crashed turn) correctly
        restarts the elapsed counter from zero.
        """
        self._turn_started[repo_id] = time.monotonic()

    def clear_turn_start(self, repo_id: str) -> None:
        """Drop the turn-start timestamp on Stop. Idempotent."""
        self._turn_started.pop(repo_id, None)

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

    def subagents(self, repo_id: str) -> int:
        return len(self._subagents.get(repo_id, ()))

    def is_session_active(self, repo_id: str) -> bool:
        return self._session_active.get(repo_id, False)

    def _in_active_group(self, repo: Repo) -> bool:
        """Rows the grouping preference floats to the top: a live terminal
        that is *also* hosting a live Claude session.

        A terminal sitting at a bare bash prompt — Claude quit, shell still
        open — is not work in progress, so it sinks with the idle rows
        instead of holding a top slot.
        """
        return repo.id in self._active_ids and self._session_active.get(repo.id, False)

    def clear_session(self, repo_id: str) -> None:
        """Tear down every per-session signal for one row.

        Same cascade as the SessionEnd hook (working spinner, DONE/
        ATTENTION dot, leftover subagent twinkle, session-active flag).
        Called on terminal-process exit because Claude Code does not
        deliver a SessionEnd hook for `/exit` (anthropics/claude-code
        #17885), so a `/exit` would otherwise leave the spinner or
        twinkle animating forever.
        """
        # The xterm process is gone, so every session it hosted is dead —
        # drop the whole live-session set, not just one id, before the
        # cascade. Otherwise a stale id would keep session_active pinned on.
        self._live_sessions.pop(repo_id, None)
        self._set_session_active(repo_id, False)

    def _set_session_active(self, repo_id: str, active: bool) -> None:
        """Flip the session-active flag and repaint the row.

        On SessionEnd we also clear `_status`, `_working`, and `_subagents`
        for the row — the session is over, so its per-session signals (the
        DONE/ATTENTION dot, a stuck working spinner, leftover subagents
        whose SubagentStop didn't arrive) are stale, and a row still
        carrying them reads as work you haven't finished.
        """
        old = self._session_active.get(repo_id, False)
        roles: list[int] = []
        if old != active:
            self._session_active[repo_id] = active
            roles.append(ROLE_SESSION_ACTIVE)
            roles.append(ROLE_ACTIVE_GROUP)
            roles.append(Qt.ToolTipRole)
        if active:
            self._session_ended.pop(repo_id, None)
        if not active:
            # Drop the recency stamp and record the exit instead, so the row
            # sinks to the bottom of the stack rather than lingering at the
            # top of the recency sort as if a turn were still pending.
            self._last_activity.pop(repo_id, None)
            self._session_ended[repo_id] = time.monotonic()
            # Cascade-clear per-session signals. Doing it directly on the
            # dicts (not via the public mutators) keeps everything inside
            # one dataChanged emission below — set_working / set_status
            # would each fire their own.
            if repo_id in self._working:
                self._working.discard(repo_id)
                roles.append(ROLE_WORKING)
                self.working_changed.emit()
            if self._status.pop(repo_id, None) is not None:
                roles.append(ROLE_STATUS)
                roles.append(ROLE_STATUS_WORD)
            self._status_word.pop(repo_id, None)
            self._pending_tool.pop(repo_id, None)
            if repo_id in self._compacting:
                self._compacting.discard(repo_id)
                roles.append(ROLE_COMPACTING)
            if self._subagents.pop(repo_id, None) is not None:
                roles.append(ROLE_SUBAGENTS)
            self._turn_started.pop(repo_id, None)
        if roles:
            # Deduplicate while preserving order — repeated roles in the
            # list don't break anything but they're noise in the signal.
            seen: list[int] = []
            for r in roles:
                if r not in seen:
                    seen.append(r)
            self._emit_changed_for_id(repo_id, seen)

    def _set_subagent(self, repo_id: str, agent_id: str, live: bool) -> None:
        """Add or remove one subagent id for a row and repaint on change.

        Removing an id that never started (out-of-order delivery, a
        subagent dispatched before ccwork launched) is a no-op.
        """
        agents = self._subagents.setdefault(repo_id, set())
        before = len(agents)
        if live:
            agents.add(agent_id)
        else:
            agents.discard(agent_id)
        if not agents:
            self._subagents.pop(repo_id, None)
        if len(agents) != before:
            self._emit_changed_for_id(repo_id, [ROLE_SUBAGENTS, Qt.ToolTipRole])

    def set_working(self, repo_id: str, working: bool) -> None:
        """Toggle the spinner for one row. No-op if state already matches."""
        was = repo_id in self._working
        if working == was:
            return
        if working:
            self._working.add(repo_id)
            self._stamp_activity(repo_id)
        else:
            self._working.discard(repo_id)
        self._emit_changed_for_id(repo_id, [ROLE_WORKING])
        # Fire the title-counter signal only on the actual edge — the
        # `if working == was: return` guard above ensures we never emit on a
        # redundant set_working(repo_id, True) when the row is already working.
        self.working_changed.emit()

    def any_working(self) -> bool:
        return bool(self._working)

    def any_subagents(self) -> bool:
        """True iff at least one repo has subagents (foreground or background)
        in flight. Used by the sidebar to keep the spinner timer ticking
        for the twinkle animation, even when no main turn is working."""
        return any(self._subagents.values())

    def working_ids(self) -> set[str]:
        """Repo ids currently flagged as working. Read-only view."""
        return set(self._working)

    def is_working(self, repo_id: str) -> bool:
        return repo_id in self._working

    def apply_hook_event(
        self, event: str, repo_id: str, payload: dict | None = None
    ) -> None:
        """Atomic per-row state transition for one Claude hook event.

        Owns the entire event → state mapping; callers don't need to know
        the per-event mutator sequence. UI side-effects (spinner timer,
        reorder scheduling) are handled by the RepoSidebar wrapper. Every
        event changes only the row whose terminal sent it.

          • UserPromptSubmit — clear any badge and compaction, mark
            working, stamp recency. Self-heals: if a prior turn never got a
            Stop, the existing working=True state is preserved (set_working
            no-ops) and touch_activity refreshes the timestamp anyway.
          • Stop — clear working and compaction, set DONE (replacing a
            permission / answer badge). Does NOT clear _subagents:
            background subagents survive past the main turn end.
          • StopFailure — runs instead of Stop on an API error: clear
            working and compaction, set ERROR with the word for `error`.
          • PermissionRequest — set ATTENTION at once and record the tool
            waiting for approval. Does NOT clear working.
          • Notification — keyed on `notification_type`: permission_prompt
            → ATTENTION; elicitation dialogs → ANSWER (cleared by the
            elicitation_complete / _response types); quota_auto_resume_stale
            / _disabled → USAGE_LIMIT (cleared by quota_auto_resume_fired).
            Other types are ignored.
          • SubagentStart / SubagentStop — add / remove `agent_id` from the
            row's live-subagent set.
          • PreCompact / PostCompact — set / clear the compaction flag.
          • SessionStart — flip _session_active[repo_id] = True. The ⠿
            ambient badge lights once no higher-priority alert masks it,
            and the row joins the floated active group.
          • SessionEnd — drop this session's id from _live_sessions[repo_id].
            Only when it was the LAST live session in the row's terminal do
            we flip _session_active = False AND cascade-clear every
            per-session signal. A nested `claude` in the same terminal must
            not wipe the outer session's spinner. The last SessionEnd also
            sinks the row to the bottom of the stack.
          • ClaudeExited — `bin/claude` saw the claude process return:
            the same full teardown as clear_session.
        """
        payload = payload if isinstance(payload, dict) else {}
        if event == EVENT_USER_PROMPT_SUBMIT:
            self.clear_status(repo_id)
            self.set_compacting(repo_id, False)
            self.set_working(repo_id, True)
            self.touch_activity(repo_id)
            self.mark_turn_start(repo_id)
        elif event == EVENT_STOP:
            self.set_working(repo_id, False)
            self.set_compacting(repo_id, False)
            self.set_status(repo_id, STATUS_DONE)
            self.clear_turn_start(repo_id)
        elif event == EVENT_STOP_FAILURE:
            self.set_working(repo_id, False)
            self.set_compacting(repo_id, False)
            self.set_status(
                repo_id, STATUS_ERROR, ERROR_WORDS.get(str(payload.get("error")), ""),
            )
            self.clear_turn_start(repo_id)
        elif event == EVENT_PERMISSION_REQUEST:
            self.set_status(repo_id, STATUS_ATTENTION)
            tool = _tool_summary(payload)
            if tool:
                self._pending_tool[repo_id] = tool
        elif event == EVENT_NOTIFICATION:
            kind = str(payload.get("notification_type", ""))
            if kind in _PERMISSION_NOTIFICATIONS:
                # PermissionRequest usually set it already; keep its tool text.
                if self._status.get(repo_id) != STATUS_ATTENTION:
                    self.set_status(repo_id, STATUS_ATTENTION)
            elif kind in _ANSWER_NOTIFICATIONS:
                self.set_status(repo_id, STATUS_ANSWER)
            elif kind in _ANSWERED_NOTIFICATIONS:
                self._clear_status_if(repo_id, STATUS_ANSWER)
            elif kind in USAGE_LIMIT_WORDS:
                self.set_status(repo_id, STATUS_USAGE_LIMIT, USAGE_LIMIT_WORDS[kind])
            elif kind in _RESUMED_NOTIFICATIONS:
                self._clear_status_if(repo_id, STATUS_USAGE_LIMIT)
        elif event == EVENT_SUBAGENT_START:
            if payload.get("agent_id"):
                self._set_subagent(repo_id, str(payload["agent_id"]), True)
        elif event == EVENT_SUBAGENT_STOP:
            if payload.get("agent_id"):
                self._set_subagent(repo_id, str(payload["agent_id"]), False)
        elif event == EVENT_PRE_COMPACT:
            self.set_compacting(repo_id, True)
        elif event == EVENT_POST_COMPACT:
            self.set_compacting(repo_id, False)
        elif event == EVENT_SESSION_START:
            sid = payload.get("session_id")
            if sid:
                self._live_sessions.setdefault(repo_id, set()).add(str(sid))
            self._set_session_active(repo_id, True)
        elif event == EVENT_SESSION_END:
            sid = payload.get("session_id")
            live = self._live_sessions.get(repo_id)
            if sid and live is not None:
                live.discard(str(sid))
            # Only tear down per-session signals when no session remains in
            # this row's terminal.
            if not self._live_sessions.get(repo_id):
                self._live_sessions.pop(repo_id, None)
                self._set_session_active(repo_id, False)
        elif event == EVENT_CLAUDE_EXITED:
            self.clear_session(repo_id)

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

    def rebind_repo(self, repo_id: str, new_path: str) -> bool:
        """Repoint one row at `new_path` via `RepoStore.rebind`. The display
        name updates implicitly because `Repo.display_name` is derived from
        `path` basename + emoji + instance. Repaints every row whose name or
        instance changed (the rebound row, and siblings on the old and new
        paths). Returns False when nothing changed.
        """
        repo = self._store.find_by_id(repo_id)
        if repo is None:
            return False
        old_path = repo.path
        before = {r.id: r.instance for r in self._store.repos}
        if not self._store.rebind(repo_id, new_path):
            return False
        self._store.save()
        if not self._store.repos_for_path(old_path):
            self._branches.pop(old_path, None)
            self._path_missing.pop(old_path, None)
        self._branches[repo.path] = repo_store.current_branch(repo.path)
        self._path_missing[repo.path] = not os.path.isdir(repo.path)
        roles = [Qt.DisplayRole, Qt.ToolTipRole, ROLE_BRANCH, ROLE_PATH_MISSING]
        for i, r in enumerate(self._store.repos):
            if r.id == repo_id or before.get(r.id) != r.instance:
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, roles)
        return True

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
            self.dataChanged.emit(idx, idx, [ROLE_HAS_TERMINAL, ROLE_ACTIVE_GROUP])

    def last_activity(self, repo_id: str) -> float:
        return self._last_activity.get(repo_id, 0.0)

    def _activity_key(self, item) -> tuple:
        """Recency ordering key for `(index, repo)`, in three tiers:

        0. Claude activity on record — most recent first.
        1. Nothing has happened here this session.
        2. A Claude session ended here — oldest exit first, so the repo you
           just quit lands at the very bottom of the stack.

        Ties break on current position, keeping the sort stable.
        """
        i, r = item
        ts = self._last_activity.get(r.id, 0.0)
        if ts > 0:
            return (0, -ts, i)
        ended = self._session_ended.get(r.id)
        if ended is not None:
            return (2, ended, i)
        return (1, 0.0, i)

    def _group_key(self, item) -> tuple:
        i, r = item
        return (0 if self._in_active_group(r) else 1, i)

    def apply_auto_arrange(self) -> bool:
        """Reorder _store.repos by Claude-activity recency desc.

        Returns True if the order changed. Selection survives via
        persistent indices. See `_activity_key` for the tiering.
        """
        return self._reorder_by(self._activity_key)

    def apply_terminal_grouping(self) -> bool:
        """Float repos with a live Claude session to the top of the list.

        Stable within each group: relative order is preserved, so this
        composes cleanly after apply_auto_arrange.
        """
        return self._reorder_by(self._group_key)

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
        for enabled, key in ((auto_arrange, self._activity_key),
                             (group_active, self._group_key)):
            if not enabled:
                continue
            indexed = sorted(enumerate(repos), key=key)
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

        for state in (self._status, self._status_word, self._pending_tool,
                      self._title_synced,
                      self._last_activity, self._session_ended,
                      self._turn_started, self._live_sessions, self._subagents,
                      self._session_active):
            state.pop(repo.id, None)
        self._working.discard(repo.id)
        self._compacting.discard(repo.id)
        remove_row_title(repo.id)
        # Path-keyed caches stay only while at least one row still uses the
        # path — drop them once the last duplicate is gone.
        if not self._store.repos_for_path(path):
            self._branches.pop(path, None)
            if self._last_focused == _norm(path):
                self._last_focused = None
        self._store.save()
        return True
