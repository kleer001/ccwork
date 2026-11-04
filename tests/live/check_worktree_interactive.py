"""Live check: interactive Claude Code sessions move a row into a worktree
and back.

Runs on its own Xvfb display (`harness.run_on_xvfb`). Makes a git repo in a
temporary folder, launches ccwork with one row on it and opens the row's
terminal with Ctrl+Shift+1. Then it types into the interactive Claude Code
screen, through the installed hook sink and the `bin/claude` wrapper:

1. `claude`, to accept the folder trust prompt (Down, Enter), then `/exit`.
   An interactive `claude -w` refuses a folder that is not trusted. Claude
   Code records the trust of the temporary folder in `~/.claude.json`.
2. `claude -w live-exit`. The script writes a file into the worktree, types
   `/exit` and picks "Remove worktree" in Claude's exit dialog. A worktree
   with no changes is removed with no dialog.
3. `claude --allowedTools EnterWorktree ExitWorktree`, with two prompts: call
   EnterWorktree, then call ExitWorktree with action remove.

Only step 3 sends prompts (two, to Haiku). The row follows the payload
`cwd` of SessionStart, UserPromptSubmit and Stop, so the script records the
row's path after each hook event. It passes when:

- after step 2's SessionStart the row is on the `live-exit` worktree, and
  after exit it is on the repo, with the worktree folder and branch gone;
- after step 3's first Stop the row is on the `live-enter` worktree, and
  after the second Stop, before ClaudeExited, it is on the repo, with the
  worktree folder and branch gone;
- at the end the row has no `home`, and `recent` is empty.

Docs: `docs/specs/worktree.md` sections 6 and 9.

    .venv/bin/python tests/live/check_worktree_interactive.py
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
EXIT_NAME = "live-exit"
ENTER_NAME = "live-enter"


def key(name: str) -> None:
    subprocess.run(["xdotool", "key", name], check=True)
    time.sleep(0.5)


def type_line(text: str) -> None:
    subprocess.run(["xdotool", "type", "--delay", "30", text], check=True)
    time.sleep(0.5)
    key("Return")


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="ccwork-wtinter-"))
    proj = harness.seed_repo(sandbox / "proj")
    exit_wt = proj / ".claude" / "worktrees" / EXIT_NAME
    enter_wt = proj / ".claude" / "worktrees" / ENTER_NAME
    evidence = harness.evidence_dir()

    cfg = sandbox / "config"
    repos_json = cfg / "ccwork" / "repos.json"
    repos_json.parent.mkdir(parents=True)
    repos_json.write_text(json.dumps({"version": 1, "repos": [{"path": str(proj), "id": "row1"}]}))
    log_path = evidence / "ccwork.log"
    env = dict(os.environ, XDG_CONFIG_HOME=str(cfg), CCWORK_LOG="INFO")
    proc = subprocess.Popen([str(REPO / ".venv/bin/python"), "-m", "src.main"], cwd=str(REPO),
                            env=env, stdout=open(log_path, "wb"), stderr=subprocess.STDOUT)
    print(f"pid={proc.pid} sandbox={sandbox}")

    def store() -> dict:
        try:
            return json.loads(repos_json.read_text())
        except json.JSONDecodeError:  # a read during ccwork's write
            return {}

    def row_path() -> str:
        return store().get("repos", [{}])[0].get("path", "")

    events: list[tuple[str, str]] = []  # (hook event, row path just after it)

    def wait_for(event: str, count: int, timeout: float = 120) -> bool:
        deadline = time.time() + timeout
        while sum(1 for e, _ in events if e == event) < count:
            if time.time() > deadline:
                print(f"FAIL: no {event} number {count} within {timeout:.0f} s")
                harness.screenshot(evidence / f"timeout-{event}-{count}.png")
                return False
            text = log_path.read_text(errors="replace") if log_path.exists() else ""
            lines = [l for l in text.splitlines() if "hook event=" in l]
            for line in lines[len(events):]:
                time.sleep(0.4)  # the handler writes repos.json after the log line
                events.append((line.split("hook event=")[1].split()[0], row_path()))
            time.sleep(0.1)
        return True

    def path_after(event: str, count: int) -> str:
        return [p for e, p in events if e == event][count - 1]

    def has_branch(name: str) -> bool:
        return harness.git("-C", str(proj), "branch", "--list", f"worktree-{name}") != ""

    branches: dict[str, bool] = {}  # worktree name -> its branch existed in the session

    try:
        deadline = time.time() + 10
        while "global keys:" not in (log_path.read_text(errors="replace") if log_path.exists() else ""):
            if time.time() > deadline:
                print("FAIL: startup")
                return 1
            time.sleep(0.1)
        harness.focus_ccwork()
        time.sleep(0.8)
        key("ctrl+shift+1")
        time.sleep(3.0)

        # 1. Accept the folder trust prompt. Its default is "No, exit".
        type_line("claude --model haiku")
        time.sleep(8)
        harness.screenshot(evidence / "trust.png")
        key("Down")
        key("Return")
        if not wait_for("SessionStart", 1):
            return 1
        time.sleep(4)
        type_line("/exit")
        if not wait_for("ClaudeExited", 1):
            return 1

        # 2. claude -w, then exit with remove.
        time.sleep(1)
        type_line(f"claude --model haiku -w {EXIT_NAME}")
        if not wait_for("SessionStart", 2):
            return 1
        time.sleep(4)
        harness.screenshot(evidence / "exit-in-worktree.png")
        branches[EXIT_NAME] = has_branch(EXIT_NAME)
        (exit_wt / "note.txt").write_text("ok\n")
        type_line("/exit")
        time.sleep(3)
        harness.screenshot(evidence / "exit-dialog.png")
        key("Down")
        key("Return")
        if not wait_for("ClaudeExited", 2):
            return 1
        time.sleep(1)
        exit_back = row_path()

        # 3. EnterWorktree, then ExitWorktree, in one session.
        type_line("claude --model haiku --allowedTools EnterWorktree ExitWorktree")
        if not wait_for("SessionStart", 3):
            return 1
        time.sleep(4)
        type_line(f"Call the EnterWorktree tool with the name {ENTER_NAME}. "
                  "Then reply with the word ok.")
        if not wait_for("Stop", 1):
            return 1
        harness.screenshot(evidence / "enter-in-worktree.png")
        branches[ENTER_NAME] = has_branch(ENTER_NAME)
        time.sleep(2)
        type_line("Call the ExitWorktree tool with action remove. Then reply with the word ok.")
        if not wait_for("Stop", 2):
            return 1
        exits_at_stop = sum(1 for e, _ in events if e == "ClaudeExited")
        harness.screenshot(evidence / "enter-back.png")
        type_line("/exit")
        if not wait_for("ClaudeExited", 3):
            return 1
        time.sleep(1)

        saved = store()
        final = saved.get("repos", [{}])[0]
        print("events and row paths:")
        for e, p in events:
            print(f"  {e:<18} {p}")
        print("final:", {k: final.get(k) for k in ("path", "home")}, "recent:", saved.get("recent"))
        checks = {
            "claude -w: row on the worktree after SessionStart": path_after("SessionStart", 2) == str(exit_wt),
            "claude -w: row back on the repo after exit": exit_back == str(proj),
            "claude -w: worktree folder removed": not exit_wt.exists(),
            "claude -w: worktree branch removed": branches[EXIT_NAME] and not has_branch(EXIT_NAME),
            "EnterWorktree: row on the worktree after the first Stop": path_after("Stop", 1) == str(enter_wt),
            "ExitWorktree: row on the repo after the second Stop": path_after("Stop", 2) == str(proj),
            "ExitWorktree: before ClaudeExited": exits_at_stop == 2,
            "ExitWorktree: worktree folder removed": not enter_wt.exists(),
            "ExitWorktree: worktree branch removed": branches[ENTER_NAME] and not has_branch(ENTER_NAME),
            "home cleared": not final.get("home"),
            "recent empty": not saved.get("recent"),
        }
        for k, v in checks.items():
            print(f"  {k}: {'OK' if v else 'FAIL'}")
        print(f"screenshots: {evidence}/*.png")
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
        for wt in (exit_wt, enter_wt):
            if wt.is_dir():
                subprocess.run(["git", "-C", str(proj), "worktree", "remove", "--force", str(wt)],
                               capture_output=True)


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
