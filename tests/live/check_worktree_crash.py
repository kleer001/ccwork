"""Live check: after a crash in an EnterWorktree session, crash recovery
records the folder that `claude --resume` needs.

Runs on its own Xvfb display (`harness.run_on_xvfb`). Makes a git repo in a
temporary folder, launches ccwork with one row on it, and types a `claude
-p` prompt that calls EnterWorktree and then runs `sleep 40`. This runs one
real Claude Code prompt. When the row is on the worktree, the script kills
ccwork (SIGKILL). It then reads the sandboxed `open_sessions.json`, and
finds the session's transcript under the Claude config dir
(`<config>/projects/*/<session id>.jsonl`). After EnterWorktree, Claude
keeps the transcript in the worktree's project folder, but `claude --resume
<id>` in the folder where the session started still finds it. The check
passes when the recorded folder is the first `cwd` of the transcript: the
folder where the session started. Claude locks its worktree while the
session runs, and a crash leaves the lock, so the cleanup unlocks it. Docs:
`docs/specs/worktree.md` sections 7 (crash recovery) and 9.

    .venv/bin/python tests/live/check_worktree_crash.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import harness

NAME = "live-crash"


def main() -> int:
    sandbox = harness.new_sandbox("wtcrash")
    proj = harness.seed_repo(sandbox / "proj")
    worktree = str(harness.claude_worktrees(proj) / NAME)
    with harness.ccwork(sandbox, [proj]) as app:
        app.open_terminal()
        harness.type_line(f"claude --allowedTools EnterWorktree 'Bash(sleep:*)' -p 'Call the "
                          f"EnterWorktree tool with the name {NAME}. Then run the shell command "
                          f"sleep 40. Then reply with the word ok.'")
        deadline = time.time() + 90
        while app.row_path() != worktree:
            if time.time() > deadline:
                print("FAIL: the row did not reach the worktree within 90 s")
                return 2
            time.sleep(0.2)
        time.sleep(2.0)   # Claude runs `sleep 40` now
        app.proc.kill()
        app.proc.wait(timeout=5)
        opened = app.config / "open_sessions.json"
        recorded = json.loads(opened.read_text()).get("open", {}) if opened.exists() else {}
        print("open sessions:", recorded)
        claude_config = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        started = {}
        for path, entry in recorded.items():
            for hit in (claude_config / "projects").glob(f"*/{entry['id']}.jsonl"):
                print("transcript:", hit.parent.name)
                for line in hit.read_text().splitlines():
                    cwd = json.loads(line).get("cwd")
                    if cwd:
                        started[path] = cwd
                        break
        print("session started in:", started)
        return harness.report({
            "one open session": len(recorded) == 1,
            "recorded folder is where the session started": bool(started) and all(
                path == cwd for path, cwd in started.items()),
        })


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
