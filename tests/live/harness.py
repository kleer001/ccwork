"""Run a live check on its own X display, away from the desktop.

`run_on_xvfb()` starts Xvfb on a free display (`-displayfd`) with openbox as
the window manager, then runs the calling script again inside it. The child
gets a temporary `XDG_RUNTIME_DIR`, so a ccwork that the script launches owns
its own hook socket and never talks to the ccwork on the desktop. The D-Bus
session address is `disabled:`, so desktop notifications stay off the
desktop. Call it first in the script's `__main__` block.

Each run keeps its evidence in the repo, in `tmp/live-runs/<check>-<time>/`
(`evidence_dir()`): the check's output, the ccwork log and the screenshots.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHILD_FLAG = "_CCWORK_LIVE_CHILD"
EVIDENCE_VAR = "_CCWORK_LIVE_EVIDENCE"
REPO = Path(__file__).resolve().parents[2]
SCREEN = "1280x900x24"  # MainWindow opens at 1280x820, plus the title bar


def run_on_xvfb() -> None:
    if os.environ.get(CHILD_FLAG) == "1":
        return
    evidence = REPO / "tmp" / "live-runs" / f"{Path(sys.argv[0]).stem}-{time.strftime('%Y%m%d-%H%M%S')}"
    evidence.mkdir(parents=True)
    read_fd, write_fd = os.pipe()
    xvfb = subprocess.Popen(
        ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", SCREEN, "-nolisten", "tcp"],
        pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(write_fd)
    with os.fdopen(read_fd) as f:
        number = f.readline().strip()
    if not number:
        xvfb.terminate()
        sys.exit("FAIL: Xvfb did not start")
    display = ":" + number
    runtime = tempfile.mkdtemp(prefix="ccwork-live-run-")
    # A check run from inside a ccwork terminal or a Claude session would
    # pass on CCWORK_CLAUDE_DEPTH (bin/claude then sends no ClaudeExited)
    # and the session's CLAUDE_CODE_* ids. The launched ccwork starts clean,
    # with the same Claude config folder.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CCWORK_", "CLAUDE")) or k == "CLAUDE_CONFIG_DIR"}
    env.update(DISPLAY=display, QT_QPA_PLATFORM="xcb", XDG_RUNTIME_DIR=runtime,
               DBUS_SESSION_BUS_ADDRESS="disabled:", **{CHILD_FLAG: "1", EVIDENCE_VAR: str(evidence)})
    env.pop("WAYLAND_DISPLAY", None)
    wm = subprocess.Popen(["openbox"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 5
        while subprocess.run(["wmctrl", "-m"], env=env, capture_output=True).returncode != 0:
            if time.time() > deadline:
                sys.exit("FAIL: openbox did not start on " + display)
            time.sleep(0.1)
        print(f"display={display} runtime={runtime} evidence={evidence}", flush=True)
        with open(evidence / "output.txt", "w") as out:
            child = subprocess.Popen([sys.executable, *sys.argv], env=env, text=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            for line in child.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                out.write(line)
            rc = child.wait()
    finally:
        for p in (wm, xvfb):
            p.terminate()
            p.wait()
        shutil.rmtree(runtime, ignore_errors=True)
    sys.exit(rc)


def evidence_dir() -> Path:
    """The repo folder that keeps this run's output, ccwork log and screenshots."""
    return Path(os.environ[EVIDENCE_VAR])


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def seed_repo(path: Path) -> Path:
    """A git repo at `path` on branch `main` with one commit of a README.
    Gives the real path, which is what hook payloads and `repos.json` hold."""
    path.mkdir(parents=True)
    git("init", "-q", "-b", "main", str(path))
    (path / "README").write_text("seed\n")
    git("-C", str(path), "add", "README")
    git("-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
    return Path(os.path.realpath(path))


def ccwork_window() -> str:
    """The id of the ccwork window, found by WM_CLASS (`main.py.ccwork`). A
    title match is not safe: a shell prompt in a title often holds "ccwork"
    as the cwd. ccwork logs its `global keys:` line before the window shows,
    so this waits for the window."""
    deadline = time.time() + 5
    while True:
        out = subprocess.run(["wmctrl", "-lx"], capture_output=True, text=True).stdout
        wid = next((l.split()[0] for l in out.splitlines() if "main.py.ccwork" in l), None)
        if wid:
            return wid
        if time.time() > deadline:
            raise RuntimeError("the ccwork window did not appear")
        time.sleep(0.1)


def focus_ccwork() -> None:
    subprocess.run(["wmctrl", "-ia", ccwork_window()], check=True)


def screenshot(path: Path) -> None:
    """Save the whole display as a PNG."""
    subprocess.run(["import", "-window", "root", str(path)], check=True)


def open_other_window(title: str) -> subprocess.Popen:
    """Start a plain xterm with a known title, as "another app" to focus."""
    proc = subprocess.Popen(["xterm", "-T", title, "-e", "sleep", "600"])
    deadline = time.time() + 5
    while title not in subprocess.run(["wmctrl", "-l"], capture_output=True, text=True).stdout:
        if time.time() > deadline:
            proc.kill()
            raise RuntimeError(f"window {title!r} did not appear")
        time.sleep(0.1)
    return proc
