"""Desktop toast choice in bin/ccwork-hook-sink.

A stub `notify-send` on PATH records its arguments. The sink runs with
CCWORK_GUI=1 and a private config dir, so the user's settings and real
desktop never see a toast.
"""

from __future__ import annotations

import json
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


# ── Row title ↔ Claude session title (sessionTitle / additionalContext) ──


def _write_title(env: dict, title: str, synced: str, row: str = "row1") -> None:
    d = Path(env["XDG_RUNTIME_DIR"]) / "ccwork" / "titles"
    d.mkdir(parents=True, exist_ok=True)
    (d / row).write_text(f"{title}\n{synced}\n")


def _hook(env: dict, event: str, payload: str, row: str = "row1") -> str:
    """Run the sink as a row's terminal would. Returns stdout (hook output)."""
    run_env = {k: v for k, v in env.items() if not k.startswith("_")}
    run_env["CCWORK_EVENT"] = event
    run_env["CCWORK_ROW_ID"] = row
    proc = subprocess.run(
        ["bash", str(SINK)],
        input=payload, text=True, capture_output=True, env=run_env,
        cwd=env["_repo"], timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_session_start_pushes_row_title_and_context(toast_env: dict) -> None:
    _write_title(toast_env, "fix login bug", "")
    out = _hook(toast_env, "SessionStart", '{"session_id":"s1","source":"startup"}')

    obj = json.loads(out)
    hso = obj["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    assert hso["sessionTitle"] == "fix login bug"
    assert "ccwork-rename" in hso["additionalContext"]


def test_user_prompt_submit_is_silent_when_titles_match(toast_env: dict) -> None:
    _write_title(toast_env, "fix login bug", "fix login bug")
    out = _hook(toast_env, "UserPromptSubmit",
                '{"session_id":"s1","session_title":"fix login bug","prompt":"hi"}')
    assert out == ""


def test_synced_row_with_different_session_title_is_silent(toast_env: dict) -> None:
    _write_title(toast_env, "mine", "mine")
    out = _hook(toast_env, "UserPromptSubmit",
                '{"session_id":"s1","session_title":"renamed in claude","prompt":"hi"}')
    assert out == ""


def test_changed_row_title_is_pushed_on_prompt(toast_env: dict) -> None:
    _write_title(toast_env, "mine", "old")
    out = _hook(toast_env, "UserPromptSubmit",
                '{"session_id":"s1","session_title":"old","prompt":"hi"}')

    hso = json.loads(out)["hookSpecificOutput"]
    assert hso == {"hookEventName": "UserPromptSubmit", "sessionTitle": "mine"}


def test_no_title_file_is_silent(toast_env: dict) -> None:
    assert _hook(toast_env, "UserPromptSubmit", '{"prompt":"hi"}') == ""


def test_prompt_text_mimicking_session_title_does_not_confuse_sink(toast_env: dict) -> None:
    # The prompt holds an escaped "session_title" equal to the row title.
    # The real payload has no session_title, so the row title must be pushed.
    _write_title(toast_env, "fix", "fix")
    payload = '{"session_id":"s1","prompt":"note: \\"session_title\\":\\"fix\\" is in my text"}'
    out = _hook(toast_env, "UserPromptSubmit", payload)

    assert json.loads(out)["hookSpecificOutput"]["sessionTitle"] == "fix"


def test_title_with_quotes_and_backslash_round_trips(toast_env: dict) -> None:
    title = 'say "hi" \\ there'
    _write_title(toast_env, title, "")

    out = _hook(toast_env, "SessionStart", '{"session_id":"s1"}')
    assert json.loads(out)["hookSpecificOutput"]["sessionTitle"] == title

    # The same title, already escaped in the payload, is not pushed again.
    _write_title(toast_env, title, title)
    payload = '{"session_id":"s1","session_title":"say \\"hi\\" \\\\ there"}'
    assert _hook(toast_env, "UserPromptSubmit", payload) == ""


def test_title_output_needs_the_gui(toast_env: dict) -> None:
    _write_title(toast_env, "fix login bug", "")
    env = dict(toast_env, CCWORK_GUI="0")
    assert _hook(env, "SessionStart", '{"session_id":"s1"}') == ""
