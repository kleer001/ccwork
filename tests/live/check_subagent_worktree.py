"""Live check: a subagent in its own worktree does not move the row.

Runs on its own Xvfb display (`harness.run_on_xvfb`). Makes a git repo in its
sandbox folder, launches ccwork with one row on it, opens the row's
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

import sys

import harness


def main() -> int:
    sandbox, proj = harness.new_project("wtsub")
    with harness.ccwork(sandbox, [proj]) as app:
        app.open_terminal()
        harness.type_line(f"{harness.CLAUDE} --allowedTools Agent -p 'Start one general-purpose subagent "
                          "with the Agent tool and isolation set to worktree. Its task: reply "
                          "with the word ok. Then reply with the word ok.'")
        counts: list[int] = []  # the worktrees listed at each sample
        seen = harness.watch_claude(app, tick=lambda: counts.append(
            harness.git("-C", str(proj), "worktree", "list", "--porcelain").count("worktree ")))
        events = app.hook_events()
        most = max(counts, default=0)
        print("most worktrees at one time:", most)
        return harness.report({
            "subagent ran": "SubagentStart" in events and "SubagentStop" in events,
            "subagent worktree existed": most >= 2,
            "row stayed": seen == [str(proj)],
            "back home": app.row_path() == str(proj),
            # The row never changes, so ccwork may never rewrite repos.json.
            "no home": not app.row().get("home"),
            "recent empty": app.recent() == [],
        })


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
