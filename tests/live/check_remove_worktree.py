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

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import harness

REPO = Path(__file__).resolve().parents[2]


def key(*keys: str) -> None:
    subprocess.run(["xdotool", "key", "--delay", "80", *keys], check=True)


def windows() -> str:
    return subprocess.run(["wmctrl", "-l"], capture_output=True, text=True).stdout


def main() -> int:
    sandbox = Path(os.path.realpath(tempfile.mkdtemp(prefix="ccwork-rmwt-")))
    proj = sandbox / "proj"
    proj.mkdir()
    harness.git("init", "-q", "-b", "main", str(proj))
    (proj / "README").write_text("seed\n")
    (proj / ".gitignore").write_text(".env\n")
    harness.git("-C", str(proj), "add", "-A")
    harness.git("-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
    clean, dirty = sandbox / "proj-clean", sandbox / "proj-dirty"
    for wt in (clean, dirty):
        harness.git("-C", str(proj), "worktree", "add", "-q", "-b", wt.name[5:], str(wt), "HEAD")
    (clean / ".env").write_text("KEY=1\n")
    (dirty / "README").write_text("edited\n")

    cfg = sandbox / "config"
    repos_json = cfg / "ccwork" / "repos.json"
    repos_json.parent.mkdir(parents=True)
    repos_json.write_text(json.dumps({"version": 1, "repos": [
        {"path": str(dirty), "id": "row1"}, {"path": str(clean), "id": "row2"}]}))
    log_path = harness.evidence_dir() / "ccwork.log"
    env = dict(os.environ, XDG_CONFIG_HOME=str(cfg), CCWORK_LOG="INFO")
    proc = subprocess.Popen([str(REPO / ".venv/bin/python"), "-m", "src.main"], cwd=str(REPO),
                            env=env, stdout=open(log_path, "wb"), stderr=subprocess.STDOUT)
    print(f"pid={proc.pid} sandbox={sandbox}")

    def remove_row(y: int, shot: str) -> None:
        subprocess.run(["xdotool", "mousemove", "--window", str(int(wid, 16)), "100", str(y),
                        "click", "3"], check=True)
        time.sleep(0.8)
        key("Up", "Return")          # the last menu item: Remove from sidebar
        time.sleep(1.0)
        key("space")                 # the check box has the focus
        time.sleep(0.4)
        harness.screenshot(harness.evidence_dir() / shot)
        key("Return")
        time.sleep(1.5)

    try:
        deadline = time.time() + 10
        while "global keys:" not in (log_path.read_text(errors="replace") if log_path.exists() else ""):
            if time.time() > deadline:
                print("FAIL: startup")
                return 1
            time.sleep(0.1)
        wid = harness.ccwork_window()
        subprocess.run(["wmctrl", "-ia", wid], check=True)
        time.sleep(0.8)

        remove_row(95, "dirty-dialog.png")
        refused = "Remove from sidebar" in windows()
        harness.screenshot(harness.evidence_dir() / "dirty-refused.png")
        after_dirty = json.loads(repos_json.read_text())
        key("Return")                # close git's message
        time.sleep(0.8)
        remove_row(165, "clean-dialog.png")
        after_clean = json.loads(repos_json.read_text())

        branches = harness.git("-C", str(proj), "branch", "--format=%(refname:short)").split()
        checks = {
            "clean folder gone": not clean.exists(),
            "clean branch gone": "clean" not in branches,
            "clean row gone": [r["id"] for r in after_clean["repos"]] == ["row1"],
            "recent empty": after_clean.get("recent") == [],
            "dirty refused with a message": refused,
            "dirty folder stays": dirty.is_dir() and "dirty" in branches,
            "dirty row stays": [r["id"] for r in after_dirty["repos"]] == ["row1", "row2"],
        }
        for k, v in checks.items():
            print(f"  {k}: {'OK' if v else 'FAIL'}")
        print(f"screenshots: {harness.evidence_dir()}/*.png")
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


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
