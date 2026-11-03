"""Live check: a row follows the EnterWorktree tool and comes back.

Runs on its own Xvfb display (`harness.run_on_xvfb`). Makes a git repo in a
temporary folder, launches ccwork with one row on it, opens the row's
terminal with Ctrl+Shift+1 and types a `claude -p` prompt that asks Claude
to call EnterWorktree, then to reply. This runs one real Claude Code
prompt, through the installed hook sink and the `bin/claude` wrapper, with
EnterWorktree allowed by `--allowedTools`. The script samples the row's
path in the sandboxed `repos.json`. It passes when the row was on the worktree while Claude ran, and is
back on the repo with no `home` and an empty `recent` after exit. Docs:
`docs/specs/worktree.md` sections 6 and 9.

    .venv/bin/python tests/live/check_enter_worktree.py
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
NAME = "live-enter"


def git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="ccwork-wtenter-"))
    proj = Path(os.path.realpath(sandbox / "proj"))
    proj.mkdir()
    git("init", "-q", "-b", "main", str(proj))
    (proj / "README").write_text("seed\n")
    git("-C", str(proj), "add", "README")
    git("-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
    worktree = str(proj / ".claude" / "worktrees" / NAME)

    cfg = sandbox / "config"
    repos_json = cfg / "ccwork" / "repos.json"
    repos_json.parent.mkdir(parents=True)
    repos_json.write_text(json.dumps({"version": 1, "repos": [{"path": str(proj), "id": "row1"}]}))
    log_path = sandbox / "ccwork.log"
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
        wid = next(l.split()[0] for l in subprocess.run(["wmctrl", "-lx"], capture_output=True,
                   text=True).stdout.splitlines() if "main.py.ccwork" in l)
        subprocess.run(["wmctrl", "-ia", wid], check=True)
        time.sleep(0.8)
        subprocess.run(["xdotool", "key", "ctrl+shift+1"], check=True)
        time.sleep(3.0)
        subprocess.run(["xdotool", "type", "--delay", "20",
                        f"claude --allowedTools EnterWorktree -p 'Call the EnterWorktree tool "
                        f"with the name {NAME}. Then reply with the word ok.'"], check=True)
        subprocess.run(["xdotool", "key", "Return"], check=True)

        seen: list[str] = []
        shot = sandbox / "in-worktree.png"
        deadline = time.time() + 120
        while "event=ClaudeExited" not in log_text():
            if time.time() > deadline:
                print("FAIL: no ClaudeExited within 120 s")
                break
            path = row().get("repos", [{}])[0].get("path")
            if path and (not seen or seen[-1] != path):
                seen.append(path)
                if path == worktree:
                    time.sleep(1.0)  # repos.json is written before the repaint
                    harness.screenshot(shot)
            time.sleep(0.05)
        time.sleep(1.0)
        end = row()
        final = end.get("repos", [{}])[0]
        print("paths seen:", seen)
        print("final:", {k: final.get(k) for k in ("path", "home")}, "recent:", end.get("recent"))
        print("hook events:", [l.split("hook event=")[1].split()[0]
                               for l in log_text().splitlines() if "hook event=" in l])
        checks = {
            "followed in": worktree in seen,
            "back home": final.get("path") == str(proj),
            "home cleared": final.get("home") == "",
            "recent empty": end.get("recent") == [],
        }
        for k, v in checks.items():
            print(f"  {k}: {'OK' if v else 'FAIL'}")
        if shot.exists():
            print(f"screenshot: {shot}")
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
            subprocess.run(["git", "-C", str(proj), "worktree", "remove", "--force", worktree],
                           capture_output=True)


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
