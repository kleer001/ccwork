"""Live verification that F1 opens the keyboard-shortcuts dialog.

Launches ccwork, focuses it, injects F1 via XTest, then verifies:
  - A new `KeyGrabFilter DISPATCH` entry appears in the log.
  - `wmctrl -l` reports a window titled `Keyboard shortcuts`.

The visible-window check guards against the dispatch firing but the
callback erroring out silently — both must hold for the user-visible
behavior to be correct.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]

_x11 = ctypes.CDLL("libX11.so.6")
_xtst = ctypes.CDLL("libXtst.so.6")

_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
_x11.XOpenDisplay.restype = ctypes.c_void_p
_x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_x11.XKeysymToKeycode.restype = ctypes.c_ubyte
_x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
_xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]

XK_F1 = 0xffbe
XK_Escape = 0xff1b


def send_bare(dpy, keysym):
    kc = _x11.XKeysymToKeycode(dpy, ctypes.c_ulong(keysym))
    _xtst.XTestFakeKeyEvent(dpy, kc, 1, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc, 0, 0)
    _x11.XSync(dpy, 0)


def focus_ccwork() -> bool:
    out = subprocess.run(["wmctrl", "-lx"], capture_output=True, text=True)
    for line in out.stdout.splitlines():
        if "main.py.ccwork" in line:
            wid = line.split()[0]
            subprocess.run(["wmctrl", "-ia", wid], check=False)
            return True
    return False


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="ccwork-f1-"))
    cfg = sandbox / "config"
    cfg.mkdir()
    log_path = sandbox / "ccwork.log"

    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(cfg)
    env["CCWORK_LOG"] = "INFO"

    proc = subprocess.Popen(
        [str(REPO / ".venv/bin/python"), "-m", "src.main"],
        cwd=str(REPO),
        env=env,
        stdout=open(log_path, "wb"),
        stderr=subprocess.STDOUT,
    )
    print(f"pid={proc.pid} sandbox={sandbox}")

    try:
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if "global keys:" in (log_path.read_text(errors="replace") if log_path.exists() else ""):
                break
            time.sleep(0.1)
        else:
            print("FAIL: startup")
            return 1
        time.sleep(0.5)
        focus_ccwork()
        time.sleep(0.6)

        dpy = _x11.XOpenDisplay(None)
        before = log_path.read_text().count("KeyGrabFilter DISPATCH")
        send_bare(dpy, XK_F1)
        time.sleep(0.6)
        after = log_path.read_text().count("KeyGrabFilter DISPATCH")

        windows = subprocess.run(
            ["wmctrl", "-l"], capture_output=True, text=True
        ).stdout.splitlines()
        kb_window = any("Keyboard shortcuts" in w for w in windows)

        print(f"  F1 dispatch fired: {after > before}")
        print(f"  Keyboard shortcuts window visible: {kb_window}")
        if not (after > before and kb_window):
            print("  windows:", windows)
            print("FAIL")
            return 2

        # Dismiss with Esc.
        send_bare(dpy, XK_Escape)
        time.sleep(0.3)
        print("result: PASS")
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
