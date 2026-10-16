"""Desktop toast choice in bin/ccwork-hook-sink.

A stub `notify-send` on PATH records its arguments. The sink runs with
CCWORK_GUI=1 and a private config dir, so the user's settings and real
desktop never see a toast.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SINK = Path(__file__).resolve().parents[1] / "bin" / "ccwork-hook-sink"


@pytest.fixture
def toast_env(tmp_path: Path) -> dict:
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    record = tmp_path / "toasts.log"
    stub = stub_dir / "notify-send"
    stub.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{record}"\n')
    stub.chmod(0o755)

    repo = tmp_path / "myrepo"
    repo.mkdir()
    return {
        "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
        "CCWORK_GUI": "1",
        "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "HOME": str(tmp_path),
        "_repo": str(repo),
        "_record": str(record),
    }


def _run(env: dict, event: str, payload: str) -> str:
    """Run the sink for one hook event. Returns the toast text, or "" when
    no toast fired."""
    run_env = {k: v for k, v in env.items() if not k.startswith("_")}
    run_env["CCWORK_EVENT"] = event
    proc = subprocess.run(
        ["bash", str(SINK)],
        input=payload, text=True, capture_output=True, env=run_env,
        cwd=env["_repo"], timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    record = Path(env["_record"])
    if not record.exists():
        return ""
    text = record.read_text()
    record.unlink()
    return text


def test_permission_prompt_toasts_needs_permission(toast_env: dict) -> None:
    out = _run(toast_env, "Notification", '{"notification_type":"permission_prompt"}')
    assert "Needs permission" in out


def test_idle_prompt_does_not_toast(toast_env: dict) -> None:
    assert _run(toast_env, "Notification", '{"notification_type":"idle_prompt"}') == ""


def test_stop_failure_toasts(toast_env: dict) -> None:
    out = _run(toast_env, "StopFailure", '{"error":"rate_limit"}')
    assert "Turn failed: API error" in out


def test_no_toast_outside_the_gui(toast_env: dict) -> None:
    env = dict(toast_env, CCWORK_GUI="0")
    assert _run(env, "StopFailure", '{"error":"rate_limit"}') == ""
