"""Live check: "Make worktree…" from the row menu makes a worktree row.

Runs on its own Xvfb display (`harness.run_on_xvfb`). Makes a git repo in a
temporary folder, with an ignored `.env`, an ignored 2 MiB `model.bin`, an
ignored `tmp/` folder and a `.venv` made by `uv venv`. Launches ccwork with one row on it, right-clicks the row,
picks "Make worktree…" with the keyboard, types `fix/a` and presses Enter.
Passes when `repos.json` has a second row on `<parent>/proj-fix-a` with the
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

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import harness

REPO = Path(__file__).resolve().parents[2]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def venv_version(folder: Path) -> str:
    cfg = folder / ".venv" / "pyvenv.cfg"
    return next((l for l in cfg.read_text().splitlines() if l.startswith("version_info")), "") \
        if cfg.exists() else ""


def key(*keys: str) -> None:
    subprocess.run(["xdotool", "key", "--delay", "60", *keys], check=True)


def main() -> int:
    sandbox = Path(os.path.realpath(tempfile.mkdtemp(prefix="ccwork-mkwt-")))
    proj = sandbox / "proj"
    proj.mkdir()
    git("init", "-q", "-b", "main", str(proj))
    (proj / "README").write_text("seed\n")
    (proj / ".gitignore").write_text(".env\nmodel.bin\ntmp/\n.venv/\n")
    git("-C", str(proj), "add", "README", ".gitignore")
    git("-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
    (proj / ".env").write_text("KEY=1\n")
    (proj / "model.bin").write_bytes(b"\0" * (2 * 1024 * 1024))
    (proj / "tmp").mkdir()
    (proj / "tmp" / "result.csv").write_text("1\n")
    subprocess.run(["uv", "venv", "-q", "--python", "3.12", str(proj / ".venv")], check=True)
    folder = sandbox / "proj-fix-a"
    out = sandbox / "terminal.txt"

    cfg = sandbox / "config"
    repos_json = cfg / "ccwork" / "repos.json"
    repos_json.parent.mkdir(parents=True)
    repos_json.write_text(json.dumps(
        {"version": 1, "repos": [{"path": str(proj), "id": "row1", "emoji": "🌱"}]}))
    log_path = sandbox / "ccwork.log"
    env = dict(os.environ, XDG_CONFIG_HOME=str(cfg), CCWORK_LOG="INFO")
    proc = subprocess.Popen([str(REPO / ".venv/bin/python"), "-m", "src.main"], cwd=str(REPO),
                            env=env, stdout=open(log_path, "wb"), stderr=subprocess.STDOUT)
    print(f"pid={proc.pid} sandbox={sandbox}")

    try:
        deadline = time.time() + 10
        while "global keys:" not in (log_path.read_text(errors="replace") if log_path.exists() else ""):
            if time.time() > deadline:
                print("FAIL: startup")
                return 1
            time.sleep(0.1)
        wid = next(l.split()[0] for l in subprocess.run(["wmctrl", "-lx"], capture_output=True,
                   text=True).stdout.splitlines() if "main.py.ccwork" in l)
        subprocess.run(["wmctrl", "-ia", wid], check=True)
        time.sleep(0.8)
        # Row 1 sits at the top of the sidebar. Menu: Reload, Clone, Make worktree…
        subprocess.run(["xdotool", "mousemove", "--window", str(int(wid, 16)), "100", "95",
                        "click", "3"], check=True)
        time.sleep(0.8)
        key("Down", "Down", "Down", "Return")
        time.sleep(1.0)
        subprocess.run(["xdotool", "type", "--delay", "40", "fix/a"], check=True)
        time.sleep(0.5)
        harness.screenshot(sandbox / "dialog.png")
        key("Return")

        deadline = time.time() + 10
        rows: list = []
        while time.time() < deadline:
            rows = json.loads(repos_json.read_text()).get("repos", [])
            if len(rows) == 2:
                break
            time.sleep(0.2)
        time.sleep(3.0)  # the new row is selected and its terminal starts
        # The dialog leaves keyboard focus off the xterm: click into it.
        subprocess.run(["xdotool", "mousemove", "--window", str(int(wid, 16)), "700", "400",
                        "click", "1"], check=True)
        time.sleep(1.0)
        subprocess.run(["xdotool", "type", "--delay", "20",
                        f"pwd > {out}; git branch --show-current >> {out}"], check=True)
        key("Return")
        time.sleep(1.5)
        harness.screenshot(sandbox / "result.png")

        lines = out.read_text().split() if out.exists() else []
        rows = json.loads(repos_json.read_text()).get("repos", [])
        new = rows[1] if len(rows) == 2 else {}
        base = subprocess.run(["git", "-C", str(folder), "config", "branch.fix/a.ccworkBase"],
                              capture_output=True, text=True).stdout.strip()
        checks = {
            "second row on the folder": new.get("path") == str(folder),
            "badge copied": new.get("emoji") == "🌱",
            "title blank": new.get("title") == "",
            "branch fix/a": folder.is_dir() and git("-C", str(folder), "branch", "--show-current") == "fix/a",
            "ccworkBase main": base == "main",
            "terminal pwd": lines[:1] == [str(folder)],
            "terminal branch": lines[1:2] == ["fix/a"],
            ".env copied": (folder / ".env").read_text() == "KEY=1\n",
            "model.bin and tmp/ not copied": not (folder / "model.bin").exists()
                                             and not (folder / "tmp").exists(),
            "venv made, same version": venv_version(folder) == venv_version(proj) != "",
        }
        for k, v in checks.items():
            print(f"  {k}: {'OK' if v else 'FAIL'}")
        print(f"screenshots: {sandbox / 'dialog.png'} {sandbox / 'result.png'}")
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
