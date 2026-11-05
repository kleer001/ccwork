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

import sys

import harness

NAME = "live-enter"

if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(harness.check_follow(NAME, f"claude --allowedTools EnterWorktree -p 'Call the "
                                        f"EnterWorktree tool with the name {NAME}. Then reply "
                                        f"with the word ok.'"))
