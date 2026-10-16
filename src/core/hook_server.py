"""QLocalServer listening for hook events from `ccwork-hook-sink` + `bin/claude`.

Wire format on the socket: one JSON object per line, terminated by `\\n`.

    {"event":"Stop","cwd":"/home/x/repo","ts":1712345678.0,"payload":{...}}
    {"event":"Notification","cwd":"/home/x/repo","ts":...,"payload":{...}}
    {"event":"RepoAdded","cwd":"/home/x/repo","ts":...}

The server emits a single `event_received(dict)` signal for each parsed line.
Unparseable lines are logged and dropped — never raised — so a bad client
can't crash the GUI.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


log = logging.getLogger(__name__)


# Hook event types emitted by ccwork-hook-sink (matches Claude Code's
# hook protocol). Centralized so handlers don't drift across call sites.
EVENT_USER_PROMPT_SUBMIT = "UserPromptSubmit"
EVENT_STOP = "Stop"
EVENT_NOTIFICATION = "Notification"
EVENT_REPO_ADDED = "RepoAdded"
# Sent by `bin/ccwork-rename`: sets the sending row's title and/or emoji.
EVENT_ROW_RENAMED = "RowRenamed"
# A turn ended on an API error. Runs instead of Stop; the payload's `error`
# field names the cause (rate_limit, overloaded, billing_error, …).
EVENT_STOP_FAILURE = "StopFailure"
# Claude is about to ask the user to approve a tool. Fires at once, unlike
# the permission_prompt Notification, which waits about six seconds.
EVENT_PERMISSION_REQUEST = "PermissionRequest"
# A subagent started or resumed. The payload's `agent_id` matches the one
# SubagentStop sends, so the model tracks a set of live agent ids.
EVENT_SUBAGENT_START = "SubagentStart"
# Fires when any subagent (foreground or background) finishes.
EVENT_SUBAGENT_STOP = "SubagentStop"
# Context compaction (manual /compact, or automatic) begins and ends.
EVENT_PRE_COMPACT = "PreCompact"
EVENT_POST_COMPACT = "PostCompact"
# Fires when a Claude session starts (user invoked `claude` in the terminal).
# Drives the "is there a live Claude session in this terminal?" axis, which
# lights the dense-braille "in claude" indicator and floats the row into the
# active group.
EVENT_SESSION_START = "SessionStart"
# Fires when a Claude session ends (/exit, Ctrl+D, etc.). Clears the
# session-active flag and any leftover per-session state (alerts, working,
# detached agents) — the session is over, those signals are stale.
EVENT_SESSION_END = "SessionEnd"
# Sent by `bin/claude` when the claude process it started returns, however
# it ended. Covers /exit, which sends no SessionEnd hook
# (anthropics/claude-code#17885).
EVENT_CLAUDE_EXITED = "ClaudeExited"


def default_socket_path() -> Path:
    """Return the path we listen on.

    Prefers `$XDG_RUNTIME_DIR/ccwork/ccwork.sock`. Falls back to
    `~/.cache/ccwork/ccwork.sock` when XDG_RUNTIME_DIR is unset (e.g. cron,
    some non-systemd sessions).
    """
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "ccwork" / "ccwork.sock"


def row_title_path(row_id: str) -> Path:
    """Where ccwork publishes one row's title for `bin/ccwork-hook-sink`.

    Two lines: the row title, then the last title ccwork and the Claude
    session agreed on. The sink compares both with the payload's
    `session_title` to decide whether to push the row title to Claude.
    """
    return default_socket_path().parent / "titles" / row_id


def write_row_title(row_id: str, title: str, synced: str) -> None:
    path = row_title_path(row_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(f"{title}\n{synced}\n")
    os.replace(tmp, path)


def remove_row_title(row_id: str) -> None:
    row_title_path(row_id).unlink(missing_ok=True)


class HookServer(QObject):
    """Listen on a Unix domain socket for JSON-line hook events."""

    event_received = Signal(dict)
    started = Signal(str)  # emits the socket path once listening
    error = Signal(str)

    def __init__(self, socket_path: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._socket_path = socket_path or default_socket_path()
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        # Per-connection line buffers keyed by id(socket). QLocalServer owns
        # the QLocalSocket objects (it sets itself as their parent), so we do
        # not manage their lifetimes ourselves.
        self._buffers: dict[int, bytearray] = {}
        self._stopped = False

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    def start(self) -> None:
        """Create parent dir, clean a stale socket, begin listening.

        Refuses to start if another live server holds the socket: the
        path is a singleton, and blindly removing it would leave the
        first instance listening on an unlinked inode — permanently
        deaf to hook events with no visible symptom beyond frozen
        sidebar state."""
        # Reset in case caller does start→stop→start cycles (tests).
        self._stopped = False
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self._socket_path.exists() and self._probe_live():
            msg = (f"another ccwork is already listening on {self._socket_path}; "
                   "hook events stay with the first instance")
            log.error(msg)
            self.error.emit(msg)
            return
        # QLocalServer won't listen on an existing path if dead; remove it.
        # removeServer is safe here: the probe said nobody is listening.
        QLocalServer.removeServer(str(self._socket_path))
        if not self._server.listen(str(self._socket_path)):
            msg = f"failed to listen on {self._socket_path}: {self._server.errorString()}"
            log.error(msg)
            self.error.emit(msg)
            return
        # Restrict to the current user — this is a personal IPC socket.
        try:
            os.chmod(self._socket_path, 0o600)
        except OSError as e:  # pragma: no cover — best-effort
            log.warning("could not chmod %s: %s", self._socket_path, e)
        self.started.emit(str(self._socket_path))

    def _probe_live(self) -> bool:
        """True if something is accepting connections on the socket path."""
        probe = QLocalSocket()
        probe.connectToServer(str(self._socket_path))
        alive = probe.waitForConnected(200)
        if alive:
            probe.disconnectFromServer()
        probe.close()
        return alive

    def stop(self) -> None:
        # Set first so any slot that fires between close() and clear() knows
        # to short-circuit without touching (potentially freed) state.
        self._stopped = True
        # Only the instance that actually listened owns the socket file —
        # a refused start() must not unlink the live instance's socket.
        owned = self._server.isListening()
        # close() also deletes child QLocalSockets through Qt's parent-owned
        # lifecycle, which disconnects all our slots safely.
        self._server.close()
        self._buffers.clear()
        if not owned:
            return
        try:
            self._socket_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:  # pragma: no cover — best-effort
            log.warning("could not remove %s: %s", self._socket_path, e)

    # ── connection handling ──

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            if conn is None:
                continue
            self._buffers[id(conn)] = bytearray()
            # Bound-method connect: Qt auto-disconnects on conn destruction.
            # Avoids lambda captures that can outlive the HookServer.
            conn.readyRead.connect(self._on_ready_read)
            conn.disconnected.connect(self._on_disconnected)

    def _on_ready_read(self) -> None:
        if self._stopped:
            return
        conn = self.sender()
        if not isinstance(conn, QLocalSocket):
            return
        buf = self._buffers.get(id(conn))
        if buf is None:
            return
        data = bytes(conn.readAll().data())
        if not data:
            return
        buf.extend(data)
        # Drain complete lines. Leave any trailing partial line in the buffer.
        while True:
            nl = buf.find(b"\n")
            if nl < 0:
                break
            line = bytes(buf[:nl])
            del buf[: nl + 1]
            self._dispatch_line(line)

    def _on_disconnected(self) -> None:
        if self._stopped:
            return
        conn = self.sender()
        if not isinstance(conn, QLocalSocket):
            return
        # Drain any final line without a trailing newline.
        buf = self._buffers.pop(id(conn), None)
        if buf:
            self._dispatch_line(bytes(buf))
        # QLocalServer parents the socket to itself; do not delete manually.

    def _dispatch_line(self, raw: bytes) -> None:
        line = raw.strip()
        if not line:
            return
        try:
            obj = json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            log.warning("dropped malformed hook line (%s): %r", e, line[:200])
            return
        if not isinstance(obj, dict):
            log.warning("dropped non-object hook line: %r", line[:200])
            return
        # Always-DEBUG payload dump — captured to ~/.cache/ccwork/hooks.log
        # via the dedicated handler installed in main.py. Lets us diagnose
        # spurious-Stop / wrong-row issues without rerunning with extra env.
        log.debug("hook payload: %r", obj)
        self.event_received.emit(obj)
