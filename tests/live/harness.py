"""Run a live check on its own X display, away from the desktop.

`run_on_xvfb()` starts Xvfb on a free display (`-displayfd`) with openbox as
the window manager, then runs the calling script again inside it. The child
gets a temporary `XDG_RUNTIME_DIR`, so a ccwork that the script launches owns
its own hook socket and never talks to the ccwork on the desktop. The D-Bus
session address is `disabled:`, so desktop notifications stay off the
desktop. Call it first in the script's `__main__` block.
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


def run_on_xvfb() -> None:
    if os.environ.get(CHILD_FLAG) == "1":
        return
    read_fd, write_fd = os.pipe()
    xvfb = subprocess.Popen(
        ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
        pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(write_fd)
    with os.fdopen(read_fd) as f:
        display = ":" + f.readline().strip()
    runtime = tempfile.mkdtemp(prefix="ccwork-live-run-")
    # A check run from inside a ccwork terminal or a Claude session would
    # pass on CCWORK_CLAUDE_DEPTH (bin/claude then sends no ClaudeExited)
    # and the session's CLAUDE_CODE_* ids. The launched ccwork starts clean,
    # with the same Claude config folder.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CCWORK_", "CLAUDE")) or k == "CLAUDE_CONFIG_DIR"}
    env.update(DISPLAY=display, QT_QPA_PLATFORM="xcb", XDG_RUNTIME_DIR=runtime,
               DBUS_SESSION_BUS_ADDRESS="disabled:", **{CHILD_FLAG: "1"})
    env.pop("WAYLAND_DISPLAY", None)
    wm = subprocess.Popen(["openbox"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 5
        while subprocess.run(["wmctrl", "-m"], env=env, capture_output=True).returncode != 0:
            if time.time() > deadline:
                sys.exit("FAIL: openbox did not start on " + display)
            time.sleep(0.1)
        print(f"display={display} runtime={runtime}", flush=True)
        rc = subprocess.run([sys.executable, *sys.argv], env=env).returncode
    finally:
        wm.terminate()
        xvfb.terminate()
        shutil.rmtree(runtime, ignore_errors=True)
    sys.exit(rc)


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
