"""`bin/claude` reports when the claude process it started exits.

The wrapper runs the real binary as a child, returns its exit code, and
sends a ClaudeExited event with the row id. A nested call (CCWORK_CLAUDE_DEPTH
already set) and a call outside the GUI exec the real binary and send
nothing. The model tears the row's session down on ClaudeExited.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from src.core.hook_server import (
    EVENT_CLAUDE_EXITED,
    EVENT_SESSION_START,
    EVENT_SUBAGENT_START,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore
from src.ui.repo_model import RepoListModel

WRAPPER = Path(__file__).resolve().parents[1] / "bin" / "claude"


class _Listener:
    """AF_UNIX server at $XDG_RUNTIME_DIR/ccwork/ccwork.sock that collects
    one JSON line per connection."""

    def __init__(self, runtime: Path) -> None:
        sock_dir = runtime / "ccwork"
        sock_dir.mkdir(parents=True)
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(str(sock_dir / "ccwork.sock"))
        self.sock.listen(8)
        self.sock.settimeout(0.2)
        self.events: list[dict] = []
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            with conn:
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
            if data.strip():
                self.events.append(json.loads(data))

    def close(self) -> list[dict]:
        self._stop = True
        self._thread.join(timeout=2)
        self.sock.close()
        return self.events


@pytest.fixture
def wrapper_env(tmp_path: Path):
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    fake = fake_bin / "claude"
    fake.write_text('#!/bin/sh\necho "depth=${CCWORK_CLAUDE_DEPTH:-}"\nexit 3\n')
    fake.chmod(0o755)
    work = tmp_path / "work"   # not a git repo: no RepoAdded
    work.mkdir()
    runtime = tmp_path / "run"
    listener = _Listener(runtime)
    env = {
        "PATH": f"{WRAPPER.parent}{os.pathsep}{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "XDG_RUNTIME_DIR": str(runtime),
        "HOME": str(tmp_path),
        "CCWORK_GUI": "1",
        "CCWORK_ROW_ID": "row-1",
    }
    yield env, work, listener
    listener.close()


def _run(env: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(WRAPPER), "--some-arg"],
        env=env, cwd=cwd, capture_output=True, text=True, timeout=20,
    )


def test_wrapper_returns_exit_code_and_sends_claude_exited(wrapper_env) -> None:
    env, work, listener = wrapper_env
    proc = _run(env, work)
    events = listener.close()

    assert proc.returncode == 3
    assert "depth=1" in proc.stdout
    assert [e["event"] for e in events] == [EVENT_CLAUDE_EXITED]
    assert events[0]["row"] == "row-1"
    assert events[0]["cwd"] == str(work)
    assert events[0]["payload"] == {"code": 3}


def test_nested_call_execs_and_sends_nothing(wrapper_env) -> None:
    env, work, listener = wrapper_env
    proc = _run({**env, "CCWORK_CLAUDE_DEPTH": "1"}, work)
    events = listener.close()

    assert proc.returncode == 3
    assert events == []


def test_outside_gui_execs_and_sends_nothing(wrapper_env) -> None:
    env, work, listener = wrapper_env
    proc = _run({**env, "CCWORK_GUI": "0"}, work)
    events = listener.close()

    assert proc.returncode == 3
    assert "depth=\n" in proc.stdout
    assert events == []


def test_claude_exited_tears_down_only_its_row(qapp, tmp_path: Path) -> None:
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path="/a"), Repo(path="/a")]
    model = RepoListModel(store)
    first, second = (r.id for r in store.repos)
    for rid in (first, second):
        model.set_terminal_active(rid, True)
        model.apply_hook_event(EVENT_SESSION_START, rid, {"session_id": f"s-{rid}"})
        model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, rid, {})
    model.apply_hook_event(EVENT_SUBAGENT_START, first, {"agent_id": "ag"})

    model.apply_hook_event(EVENT_CLAUDE_EXITED, first, {"code": 0})

    assert model.is_working(first) is False
    assert model.is_session_active(first) is False
    assert model.subagents(first) == 0
    assert model.is_working(second) is True
    assert model.is_session_active(second) is True
