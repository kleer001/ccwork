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
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import harness

REPO = Path(__file__).resolve().parents[2]
NAME = "live-crash"


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="ccwork-wtcrash-"))
    proj = harness.seed_repo(sandbox / "proj")
    worktree = str(proj / ".claude" / "worktrees" / NAME)

    cfg = sandbox / "config"
    repos_json = cfg / "ccwork" / "repos.json"
    repos_json.parent.mkdir(parents=True)
    repos_json.write_text(json.dumps({"version": 1, "repos": [{"path": str(proj), "id": "row1"}]}))
    log_path = harness.evidence_dir() / "ccwork.log"
    env = dict(os.environ, XDG_CONFIG_HOME=str(cfg), CCWORK_LOG="INFO")
    proc = subprocess.Popen([str(REPO / ".venv/bin/python"), "-m", "src.main"], cwd=str(REPO),
                            env=env, stdout=open(log_path, "wb"), stderr=subprocess.STDOUT)
    print(f"pid={proc.pid} sandbox={sandbox}")

    def log_text() -> str:
        return log_path.read_text(errors="replace") if log_path.exists() else ""

    def row() -> dict:
        try:
            return json.loads(repos_json.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    try:
        deadline = time.time() + 10
        while "global keys:" not in log_text():
            if time.time() > deadline:
                print("FAIL: startup")
                return 1
            time.sleep(0.1)
        wid = harness.ccwork_window()
        subprocess.run(["wmctrl", "-ia", wid], check=True)
        time.sleep(0.8)
        subprocess.run(["xdotool", "key", "ctrl+shift+1"], check=True)
        time.sleep(3.0)
        subprocess.run(["xdotool", "type", "--delay", "20",
                        f"claude --allowedTools EnterWorktree 'Bash(sleep:*)' -p 'Call the "
                        f"EnterWorktree tool with the name {NAME}. Then run the shell command "
                        f"sleep 40. Then reply with the word ok.'"], check=True)
        subprocess.run(["xdotool", "key", "Return"], check=True)

        opened = cfg / "ccwork" / "open_sessions.json"
        deadline = time.time() + 90
        while row().get("repos", [{}])[0].get("path") != worktree:
            if time.time() > deadline:
                print("FAIL: the row did not reach the worktree within 90 s")
                return 2
            time.sleep(0.2)
        time.sleep(2.0)   # Claude runs `sleep 40` now
        proc.kill()
        proc.wait(timeout=5)
        doc = json.loads(opened.read_text()) if opened.exists() else {}
        recorded = doc.get("open", {})
        print("open sessions:", recorded)
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        started = {}
        for path, entry in recorded.items():
            for hit in (config / "projects").glob(f"*/{entry['id']}.jsonl"):
                print("transcript:", hit.parent.name)
                for line in hit.read_text().splitlines():
                    cwd = json.loads(line).get("cwd")
                    if cwd:
                        started[path] = cwd
                        break
        print("session started in:", started)
        checks = {
            "one open session": len(recorded) == 1,
            "recorded folder is where the session started": bool(started) and all(
                path == cwd for path, cwd in started.items()),
        }
        for k, v in checks.items():
            print(f"  {k}: {'OK' if v else 'FAIL'}")
        result = all(checks.values())
        print(f"\nresult: {'PASS' if result else 'FAIL'}")
        return 0 if result else 2
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        if os.path.isdir(worktree):
            subprocess.run(["git", "-C", str(proj), "worktree", "unlock", worktree],
                           capture_output=True)
            subprocess.run(["git", "-C", str(proj), "worktree", "remove", "--force", worktree],
                           capture_output=True)


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
