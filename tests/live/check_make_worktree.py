"""Live check: "Make worktree…" from the row menu makes a worktree row.

Runs on its own Xvfb display (`harness.run_on_xvfb`). Makes a git repo in its
sandbox folder, with an ignored `.env`, an ignored 2 MiB `model.bin`, an
ignored `tmp/` folder and a `.venv` made by `uv venv`. Launches ccwork with one
row on it and the worktree folder setting at `<sandbox>/worktrees`,
right-clicks the row, picks "Make worktree…" with the keyboard, types
`fix/a` and presses Enter. Passes when `repos.json` has a second row on
`<sandbox>/worktrees/proj-fix-a` with the
first row's badge, the folder is on branch `fix/a` with
`branch.fix/a.ccworkBase = main`, the new row's terminal prints that
folder for `pwd` and `fix/a` for `git branch --show-current`, and only
`.env` of the ignored entries is in the worktree, and the terminal made a
`.venv` there with the same Python version. Saves a screenshot of the
result, which shows the copy report and the setup commands. Docs:
`docs/specs/worktree.md` 5.1 to 5.5.

    .venv/bin/python tests/live/check_make_worktree.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import harness


def venv_version(folder: Path) -> str:
    cfg = folder / ".venv" / "pyvenv.cfg"
    return next((l for l in cfg.read_text().splitlines() if l.startswith("version_info")), "") \
        if cfg.exists() else ""


def main() -> int:
    sandbox = harness.new_sandbox("mkwt")
    proj = harness.seed_repo(sandbox / "proj", ignore=".env\nmodel.bin\ntmp/\n.venv/\n")
    (proj / ".env").write_text("KEY=1\n")
    (proj / "model.bin").write_bytes(b"\0" * (2 * 1024 * 1024))
    (proj / "tmp").mkdir()
    (proj / "tmp" / "result.csv").write_text("1\n")
    subprocess.run(["uv", "venv", "-q", "--python", "3.12", str(proj / ".venv")], check=True)
    folder = sandbox / "worktrees" / "proj-fix-a"
    out = sandbox / "terminal.txt"

    with harness.ccwork(sandbox, [{"path": str(proj), "emoji": "🌱"}],
                        settings=f'[ui]\nworktree_folder = "{sandbox / "worktrees"}"\n') as app:
        # Row 1 sits at the top of the sidebar. Menu: Reload, Clone, Make worktree…
        app.click(100, 95, button=3)
        harness.key("Down", "Down", "Down", "Return", pause=1.0)
        harness.type_text("fix/a")
        harness.screenshot("dialog.png")
        harness.key("Return", pause=0)

        deadline = time.time() + 10
        while len(app.store().get("repos", [])) != 2 and time.time() < deadline:
            time.sleep(0.2)
        time.sleep(3.0)  # the new row is selected and its terminal starts
        # No click: the new terminal takes the keyboard focus when it maps.
        harness.type_line(f"pwd > {out}; git branch --show-current >> {out}")
        time.sleep(1.0)
        harness.screenshot("result.png")

        lines = out.read_text().split() if out.exists() else []
        rows = app.store().get("repos", [])
        new = rows[1] if len(rows) == 2 else {}
        base = subprocess.run(["git", "-C", str(folder), "config", "branch.fix/a.ccworkBase"],
                              capture_output=True, text=True).stdout.strip()
        return harness.report({
            "second row on the folder": new.get("path") == str(folder),
            "badge copied": new.get("emoji") == "🌱",
            "title blank": new.get("title") == "",
            "branch fix/a": folder.is_dir() and harness.git("-C", str(folder), "branch", "--show-current") == "fix/a",
            "ccworkBase main": base == "main",
            "terminal pwd": lines[:1] == [str(folder)],
            "terminal branch": lines[1:2] == ["fix/a"],
            ".env copied": (folder / ".env").read_text() == "KEY=1\n",
            "model.bin and tmp/ not copied": not (folder / "model.bin").exists()
                                             and not (folder / "tmp").exists(),
            "venv made, same version": venv_version(folder) == venv_version(proj) != "",
        })


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
