"""Live check: a row follows `claude -w` into its worktree and comes back.

Runs on its own Xvfb display (`harness.run_on_xvfb`). Makes a git repo in a
temporary folder, launches ccwork with one row on it, opens the row's
terminal with Ctrl+Shift+1 and types `claude -w <name> -p <prompt>`. This
runs one real Claude Code prompt, through the installed hook sink and the
`bin/claude` wrapper. The script samples the row's path in the sandboxed
`repos.json` and passes when the row was on the worktree while Claude ran,
and is back on the repo with no `home` and an empty `recent` after exit.
Docs: `docs/specs/worktree.md` section 6.

    .venv/bin/python tests/live/check_worktree_follow.py
"""

import sys

import harness

NAME = "live-follow"

if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(harness.check_follow(NAME, f"claude -w {NAME} -p 'Reply with the word ok.'"))
