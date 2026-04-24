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


def default_socket_path() -> Path:
    """Return the path we listen on.

    Prefers `$XDG_RUNTIME_DIR/ccwork/ccwork.sock`. Falls back to
    `~/.cache/ccwork/ccwork.sock` when XDG_RUNTIME_DIR is unset (e.g. cron,
    some non-systemd sessions).
    """
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "ccwork" / "ccwork.sock"


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
        """Create parent dir, clean a stale socket, begin listening."""
        # Reset in case caller does start→stop→start cycles (tests).
        self._stopped = False
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        # QLocalServer won't listen on an existing path even if dead; remove it.
        # removeServer is safe: it only deletes the named-pipe/socket file.
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

    def stop(self) -> None:
        # Set first so any slot that fires between close() and clear() knows
        # to short-circuit without touching (potentially freed) state.
        self._stopped = True
        # close() also deletes child QLocalSockets through Qt's parent-owned
        # lifecycle, which disconnects all our slots safely.
        self._server.close()
        self._buffers.clear()
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
        self.event_received.emit(obj)
