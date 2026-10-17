"""bin/ccwork-rename: argument handling and the RowRenamed line it sends.

A real AF_UNIX listener stands in for the ccwork socket at
$XDG_RUNTIME_DIR/ccwork/ccwork.sock (autouse fixture in conftest). The
listener records each connection's bytes; the tests parse the one line.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
from pathlib import Path

import pytest

RENAME = Path(__file__).resolve().parents[1] / "bin" / "ccwork-rename"
ROW = "row-abc123"


@pytest.fixture
def env(tmp_path: Path) -> dict:
    run_dir = Path(os.environ["XDG_RUNTIME_DIR"])
    (run_dir / "ccwork").mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "XDG_RUNTIME_DIR": str(run_dir),
        "CCWORK_GUI": "1",
        "CCWORK_ROW_ID": ROW,
    }


def _run(env: dict, *args: str, listen: bool = True) -> tuple[subprocess.CompletedProcess, list[dict]]:
    """Run ccwork-rename, return (process, JSON objects received by the socket)."""
    sock_path = Path(env["XDG_RUNTIME_DIR"]) / "ccwork" / "ccwork.sock"
    received: list[bytes] = []
    srv = None
    thread = None
    if listen:
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.listen(1)
        srv.settimeout(10)

        def accept_one() -> None:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                chunks = []
                while True:
                    data = conn.recv(4096)
                    if not data:
                        break
                    chunks.append(data)
                received.append(b"".join(chunks))

        thread = threading.Thread(target=accept_one, daemon=True)
        thread.start()

    try:
        proc = subprocess.run(
            ["bash", str(RENAME), *args],
            capture_output=True, text=True, env=env, timeout=20,
        )
        if thread is not None:
            thread.join(timeout=10)
    finally:
        if srv is not None:
            srv.close()
            if sock_path.exists():
                sock_path.unlink()

    lines = [ln for blob in received for ln in blob.decode().splitlines() if ln.strip()]
    return proc, [json.loads(ln) for ln in lines]


# ── refusals ──


def test_exits_1_outside_ccwork(env: dict) -> None:
    proc, sent = _run(dict(env, CCWORK_GUI="0"), "x", listen=False)
    assert proc.returncode == 1
    assert "not inside a ccwork terminal" in proc.stderr
    assert sent == []


def test_exits_1_without_row_id(env: dict) -> None:
    env = {k: v for k, v in env.items() if k != "CCWORK_ROW_ID"}
    proc, _ = _run(env, "x", listen=False)
    assert proc.returncode == 1
    assert "not inside a ccwork terminal" in proc.stderr


@pytest.mark.parametrize("args", [
    [],
    ["--badge"],
    ["a", "b"],
    ["--badge", "🐛", "a", "b"],
])
def test_usage_errors_exit_1(env: dict, args: list[str]) -> None:
    proc, sent = _run(env, *args, listen=False)
    assert proc.returncode == 1
    assert "usage: ccwork-rename" in proc.stderr
    assert sent == []


def test_missing_socket_exits_1(env: dict) -> None:
    proc, sent = _run(env, "fix login bug", listen=False)
    assert proc.returncode == 1
    assert "socket not found" in proc.stderr
    assert sent == []


# ── the line it sends ──


def _only(sent: list[dict]) -> dict:
    assert len(sent) == 1, sent
    return sent[0]


def test_title_only_sends_only_the_title(env: dict) -> None:
    proc, sent = _run(env, "fix login bug")
    assert proc.returncode == 0, proc.stderr
    msg = _only(sent)
    assert msg["event"] == "RowRenamed"
    assert msg["row"] == ROW
    assert isinstance(msg["ts"], int)
    assert msg["payload"] == {"title": "fix login bug"}


def test_badge_only_sends_only_the_emoji(env: dict) -> None:
    proc, sent = _run(env, "--badge", "🐛")
    assert proc.returncode == 0, proc.stderr
    msg = _only(sent)
    assert msg["payload"] == {"emoji": "🐛"}


def test_badge_and_title_send_both(env: dict) -> None:
    proc, sent = _run(env, "--badge", "🐛", 'fix "login" bug')
    assert proc.returncode == 0, proc.stderr
    msg = _only(sent)
    assert msg["payload"] == {"emoji": "🐛", "title": 'fix "login" bug'}


def test_empty_title_sends_an_empty_title_field(env: dict) -> None:
    proc, sent = _run(env, "")
    assert proc.returncode == 0, proc.stderr
    msg = _only(sent)
    assert msg["payload"] == {"title": ""}


def test_empty_badge_sends_an_empty_emoji_field(env: dict) -> None:
    proc, sent = _run(env, "--badge", "")
    assert proc.returncode == 0, proc.stderr
    msg = _only(sent)
    assert msg["payload"] == {"emoji": ""}
