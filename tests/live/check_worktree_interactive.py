"""Live check: interactive Claude Code sessions move a row into a worktree
and back.

Runs on its own Xvfb display (`harness.run_on_xvfb`). Makes a git repo in its
sandbox folder, launches ccwork with one row on it and opens the row's
terminal with Ctrl+Shift+1. Then it types into the interactive Claude Code
screen, through the installed hook sink and the `bin/claude` wrapper:

1. `claude`, to accept the folder trust prompt (Down, Enter), then `/exit`.
   An interactive `claude -w` refuses a repo folder that is not trusted;
   the trust of the ccwork folder above the sandbox does not count. Claude
   Code records the trust of the sandbox repo in `~/.claude.json`.
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

import sys
import time

import harness

EXIT_NAME = "live-exit"
ENTER_NAME = "live-enter"


def main() -> int:
    sandbox = harness.new_sandbox("wtinter")
    proj = harness.seed_repo(sandbox / "proj")
    exit_wt = harness.claude_worktrees(proj) / EXIT_NAME
    enter_wt = harness.claude_worktrees(proj) / ENTER_NAME
    events: list[tuple[str, str]] = []  # (hook event, row path just after it)
    branches: dict[str, bool] = {}  # worktree name -> its branch existed in the session

    def has_branch(name: str) -> bool:
        return harness.git("-C", str(proj), "branch", "--list", f"worktree-{name}") != ""

    with harness.ccwork(sandbox, [proj]) as app:

        def wait_for(event: str, count: int) -> bool:
            deadline = time.time() + harness.CLAUDE_TIMEOUT_S
            while sum(1 for e, _ in events if e == event) < count:
                if time.time() > deadline:
                    print(f"FAIL: no {event} number {count} within {harness.CLAUDE_TIMEOUT_S} s")
                    harness.screenshot(f"timeout-{event}-{count}.png")
                    return False
                for name in app.hook_events()[len(events):]:
                    time.sleep(0.4)  # the handler writes repos.json after the log line
                    events.append((name, app.row_path()))
                time.sleep(0.1)
            return True

        def path_after(event: str, count: int) -> str:
            return [p for e, p in events if e == event][count - 1]

        app.open_terminal()

        # 1. Accept the folder trust prompt. Its default is "No, exit".
        harness.type_line(f"{harness.CLAUDE} --model haiku")
        time.sleep(8)
        harness.screenshot("trust.png")
        harness.key("Down")
        harness.key("Return")
        if not wait_for("SessionStart", 1):
            return 1
        time.sleep(4)
        harness.type_line("/exit")
        if not wait_for("ClaudeExited", 1):
            return 1

        # 2. claude -w, then exit with remove.
        time.sleep(1)
        harness.type_line(f"{harness.CLAUDE} --model haiku -w {EXIT_NAME}")
        if not wait_for("SessionStart", 2):
            return 1
        time.sleep(4)
        harness.screenshot("exit-in-worktree.png")
        branches[EXIT_NAME] = has_branch(EXIT_NAME)
        (exit_wt / "note.txt").write_text("ok\n")
        harness.type_line("/exit")
        time.sleep(3)
        harness.screenshot("exit-dialog.png")
        harness.key("Down")
        harness.key("Return")
        if not wait_for("ClaudeExited", 2):
            return 1
        time.sleep(1)
        exit_back = app.row_path()

        # 3. EnterWorktree, then ExitWorktree, in one session.
        harness.type_line(f"{harness.CLAUDE} --model haiku --allowedTools EnterWorktree ExitWorktree")
        if not wait_for("SessionStart", 3):
            return 1
        time.sleep(4)
        harness.type_line(f"Call the EnterWorktree tool with the name {ENTER_NAME}. "
                          "Then reply with the word ok.")
        if not wait_for("Stop", 1):
            return 1
        harness.screenshot("enter-in-worktree.png")
        branches[ENTER_NAME] = has_branch(ENTER_NAME)
        time.sleep(2)
        harness.type_line("Call the ExitWorktree tool with action remove. Then reply with the word ok.")
        if not wait_for("Stop", 2):
            return 1
        exits_at_stop = sum(1 for e, _ in events if e == "ClaudeExited")
        harness.screenshot("enter-back.png")
        harness.type_line("/exit")
        if not wait_for("ClaudeExited", 3):
            return 1
        time.sleep(1)

        print("events and row paths:")
        for e, p in events:
            print(f"  {e:<18} {p}")
        print("final:", {k: app.row().get(k) for k in ("path", "home")},
              "recent:", app.store().get("recent"))
        return harness.report({
            "claude -w: row on the worktree after SessionStart": path_after("SessionStart", 2) == str(exit_wt),
            "claude -w: row back on the repo after exit": exit_back == str(proj),
            "claude -w: worktree folder removed": not exit_wt.exists(),
            "claude -w: worktree branch removed": branches[EXIT_NAME] and not has_branch(EXIT_NAME),
            "EnterWorktree: row on the worktree after the first Stop": path_after("Stop", 1) == str(enter_wt),
            "ExitWorktree: row on the repo after the second Stop": path_after("Stop", 2) == str(proj),
            "ExitWorktree: before ClaudeExited": exits_at_stop == 2,
            "ExitWorktree: worktree folder removed": not enter_wt.exists(),
            "ExitWorktree: worktree branch removed": branches[ENTER_NAME] and not has_branch(ENTER_NAME),
            "home cleared": not app.row().get("home"),
            "recent empty": not app.store().get("recent"),
        })


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
