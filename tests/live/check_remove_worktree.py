"""Live check: "Remove from sidebar" with the delete box on a worktree row.

Runs on its own Xvfb display (`harness.run_on_xvfb`). Makes a repo with two
worktrees: `clean` (an ignored `.env` only) and `dirty` (an edited tracked
file). Launches ccwork with a row on each (dirty first), then for each row
right-clicks, picks "Remove from sidebar" (the last menu item), ticks the
box and presses Enter. Passes when git refuses the dirty one (a message
window opens, and its folder and row stay), and when the clean worktree's
folder, branch and row are gone and `recent` is empty. The dirty row goes
first because no terminal runs yet: a terminal that starts takes the focus.
Docs: `docs/specs/worktree.md` 7.

    .venv/bin/python tests/live/check_remove_worktree.py
"""

from __future__ import annotations

import sys

import harness


def main() -> int:
    sandbox, proj = harness.new_project("rmwt", ignore=".env\n")
    clean, dirty = sandbox / "proj-clean", sandbox / "proj-dirty"
    for branch, wt in (("clean", clean), ("dirty", dirty)):
        harness.git("-C", str(proj), "worktree", "add", "-q", "-b", branch, str(wt), "HEAD")
    (clean / ".env").write_text("KEY=1\n")
    (dirty / "README").write_text("edited\n")

    def titled_remove() -> set[str]:
        """The ids of the windows titled "Remove from sidebar": the dialog,
        and git's refusal message after it."""
        return {l.split()[0] for l in harness.windows().splitlines() if "Remove from sidebar" in l}

    with harness.ccwork(sandbox, [dirty, clean]) as app:

        def remove_row(y: int, shot: str) -> set[str]:
            """Remove the row at `y` with the delete box on. Gives the ids that
            `titled_remove` gives before Enter: the dialog."""
            app.click(100, y, button=3)
            harness.key("Up", "Return", pause=1.0)  # the last menu item: Remove from sidebar
            harness.key("space", pause=0.4)         # the check box has the focus
            harness.screenshot(shot)
            dialog = titled_remove()
            harness.key("Return", pause=1.5)
            return dialog

        dialog = remove_row(95, "dirty-dialog.png")
        # The refusal message has the dialog's title, so it must be a new window.
        refused = bool(dialog) and bool(titled_remove() - dialog)
        harness.screenshot("dirty-refused.png")
        after_dirty = app.store()
        harness.key("Return", pause=0.8)  # close git's message
        remove_row(165, "clean-dialog.png")
        after_clean = app.store()

        branches = harness.git("-C", str(proj), "branch", "--format=%(refname:short)").split()
        return harness.report({
            "clean folder gone": not clean.exists(),
            "clean branch gone": "clean" not in branches,
            "clean row gone": [r["id"] for r in after_clean["repos"]] == ["row1"],
            "recent empty": app.recent() == [],
            "dirty refused with a message": refused,
            "dirty folder stays": dirty.is_dir() and "dirty" in branches,
            "dirty row stays": [r["id"] for r in after_dirty["repos"]] == ["row1", "row2"],
        })


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
