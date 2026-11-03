"""Live check: a subagent in its own worktree does not move the row.

Runs on its own Xvfb display (`harness.run_on_xvfb`). Makes a git repo in a
temporary folder, launches ccwork with one row on it, opens the row's
terminal with Ctrl+Shift+1 and types a `claude -p` prompt that asks Claude
to start a subagent with `isolation: worktree`. This runs one real Claude
Code prompt, through the installed hook sink and the `bin/claude` wrapper.
The script samples the row's path in the sandboxed `repos.json` and the
repo's `git worktree list` (Claude removes an unchanged subagent worktree
at the end). It passes when SubagentStart and SubagentStop arrived, a
second worktree existed during the run, the row never left the repo,
and `home` and `recent` stay empty. Docs: `docs/specs/worktree.md` sections
6 (C2) and 9.

    .venv/bin/python tests/live/check_subagent_worktree.py
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



def git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="ccwork-wtsub-"))
    proj = Path(os.path.realpath(sandbox / "proj"))
    proj.mkdir()
    git("init", "-q", "-b", "main", str(proj))
    (proj / "README").write_text("seed\n")
    git("-C", str(proj), "add", "README")
    git("-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
    worktrees = proj / ".claude" / "worktrees"

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
                        "claude --allowedTools Agent -p 'Start one general-purpose subagent "
                        "with the Agent tool and isolation set to worktree. Its task: reply "
                        "with the word ok. Then reply with the word ok.'"], check=True)
        subprocess.run(["xdotool", "key", "Return"], check=True)

        seen: list[str] = []
        most_worktrees = 0
        deadline = time.time() + 120
        while "event=ClaudeExited" not in log_text():
            if time.time() > deadline:
                print("FAIL: no ClaudeExited within 120 s")
                break
            path = row().get("repos", [{}])[0].get("path")
            if path and (not seen or seen[-1] != path):
                seen.append(path)
            listed = subprocess.run(["git", "-C", str(proj), "worktree", "list", "--porcelain"],
                                    capture_output=True, text=True).stdout
            most_worktrees = max(most_worktrees, listed.count("worktree "))
            time.sleep(0.2)
        time.sleep(1.0)
        end = row()
        final = end.get("repos", [{}])[0]
        print("paths seen:", seen)
        print("final:", {k: final.get(k) for k in ("path", "home")}, "recent:", end.get("recent"))
        print("hook events:", [l.split("hook event=")[1].split()[0]
                               for l in log_text().splitlines() if "hook event=" in l])
        events = [l.split("hook event=")[1].split()[0]
                  for l in log_text().splitlines() if "hook event=" in l]
        print("most worktrees at one time:", most_worktrees)
        checks = {
            "subagent ran": "SubagentStart" in events and "SubagentStop" in events,
            "subagent worktree existed": most_worktrees >= 2,
            "row stayed": seen == [str(proj)],
            "back home": final.get("path") == str(proj),
            # The row never changes, so ccwork may never rewrite repos.json.
            "no home": not final.get("home"),
            "recent empty": not end.get("recent"),
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
        for wt in (worktrees.iterdir() if worktrees.is_dir() else []):
            subprocess.run(["git", "-C", str(proj), "worktree", "remove", "--force", str(wt)],
                           capture_output=True)


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
