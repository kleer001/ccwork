"""Integration tests for HookServer via an actual QLocalSocket client."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Headless Qt for CI / no-display environments.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

from src.core.hook_server import (
    EVENT_NOTIFICATION,
    EVENT_REPO_ADDED,
    EVENT_STOP,
    HookServer,
    default_socket_path,
)


@pytest.fixture(scope="session")
def qapp() -> QCoreApplication:
    # Use QApplication (superset of QCoreApplication) so GUI tests elsewhere
    # in the session can share the same instance — Qt forbids switching
    # from QCoreApplication to QApplication within a single process.
    return QApplication.instance() or QApplication([])


def _spin(app: QCoreApplication, ms: int = 200) -> None:
    """Pump the event loop briefly."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _send(sock_path: Path, obj: dict) -> None:
    client = QLocalSocket()
    client.connectToServer(str(sock_path))
    assert client.waitForConnected(1000), f"client connect failed: {client.errorString()}"
    payload = (json.dumps(obj) + "\n").encode("utf-8")
    assert client.write(payload) == len(payload)
    assert client.waitForBytesWritten(1000)
    client.disconnectFromServer()
    client.close()


def test_default_socket_path_prefers_xdg_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert default_socket_path() == tmp_path / "ccwork" / "ccwork.sock"


def test_default_socket_path_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert default_socket_path() == Path.home() / ".cache" / "ccwork" / "ccwork.sock"


def test_server_starts_and_receives_event(qapp: QCoreApplication, tmp_path: Path) -> None:
    sock = tmp_path / "ccwork.sock"
    srv = HookServer(socket_path=sock)
    events: list[dict] = []
    srv.event_received.connect(events.append)
    srv.start()
    assert sock.exists()

    _send(sock, {"event": EVENT_STOP, "cwd": "/tmp/x", "ts": 1.0})
    _spin(qapp)

    assert len(events) == 1
    assert events[0]["event"] == EVENT_STOP
    srv.stop()
    assert not sock.exists()


def test_server_handles_multiple_lines_in_one_send(qapp: QCoreApplication, tmp_path: Path) -> None:
    sock = tmp_path / "ccwork.sock"
    srv = HookServer(socket_path=sock)
    events: list[dict] = []
    srv.event_received.connect(events.append)
    srv.start()

    client = QLocalSocket()
    client.connectToServer(str(sock))
    assert client.waitForConnected(1000)
    payload = (
        json.dumps({"event": EVENT_STOP, "n": 1}) + "\n"
        + json.dumps({"event": EVENT_NOTIFICATION, "n": 2}) + "\n"
        + json.dumps({"event": EVENT_REPO_ADDED, "n": 3}) + "\n"
    ).encode("utf-8")
    client.write(payload)
    client.waitForBytesWritten(1000)
    client.disconnectFromServer()
    _spin(qapp)

    assert [e["n"] for e in events] == [1, 2, 3]
    srv.stop()


def test_server_handles_split_writes(qapp: QCoreApplication, tmp_path: Path) -> None:
    """A single JSON line split across two socket writes still dispatches once."""
    sock = tmp_path / "ccwork.sock"
    srv = HookServer(socket_path=sock)
    events: list[dict] = []
    srv.event_received.connect(events.append)
    srv.start()

    client = QLocalSocket()
    client.connectToServer(str(sock))
    assert client.waitForConnected(1000)
    blob = json.dumps({"event": EVENT_STOP, "cwd": "/x", "ts": 1}) + "\n"
    half = len(blob) // 2
    client.write(blob[:half].encode("utf-8"))
    client.waitForBytesWritten(500)
    _spin(qapp, 50)
    client.write(blob[half:].encode("utf-8"))
    client.waitForBytesWritten(500)
    _spin(qapp)

    assert len(events) == 1
    srv.stop()


def test_server_ignores_malformed_json(qapp: QCoreApplication, tmp_path: Path) -> None:
    sock = tmp_path / "ccwork.sock"
    srv = HookServer(socket_path=sock)
    events: list[dict] = []
    srv.event_received.connect(events.append)
    srv.start()

    client = QLocalSocket()
    client.connectToServer(str(sock))
    assert client.waitForConnected(1000)
    client.write(b"not-json\n")
    client.write((json.dumps({"event": EVENT_STOP}) + "\n").encode("utf-8"))
    # Valid JSON but not an object — should be rejected.
    client.write(b"[1, 2, 3]\n")
    client.waitForBytesWritten(500)
    client.disconnectFromServer()
    _spin(qapp)

    assert len(events) == 1
    assert events[0]["event"] == EVENT_STOP
    srv.stop()


def test_server_cleans_stale_socket_file(qapp: QCoreApplication, tmp_path: Path) -> None:
    """Starting the server over a stale socket file must succeed."""
    sock = tmp_path / "ccwork.sock"
    sock.parent.mkdir(parents=True, exist_ok=True)
    sock.write_bytes(b"")
    srv = HookServer(socket_path=sock)
    srv.start()
    _send(sock, {"event": EVENT_STOP})
    _spin(qapp)
    srv.stop()


def test_server_accepts_trailing_line_without_newline(qapp: QCoreApplication, tmp_path: Path) -> None:
    sock = tmp_path / "ccwork.sock"
    srv = HookServer(socket_path=sock)
    events: list[dict] = []
    srv.event_received.connect(events.append)
    srv.start()

    client = QLocalSocket()
    client.connectToServer(str(sock))
    assert client.waitForConnected(1000)
    # No trailing newline — server should drain on disconnect.
    client.write(json.dumps({"event": EVENT_STOP}).encode("utf-8"))
    client.waitForBytesWritten(500)
    client.disconnectFromServer()
    _spin(qapp)

    assert len(events) == 1
    srv.stop()
