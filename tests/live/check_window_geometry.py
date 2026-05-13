"""Live verification that window.geometry is persisted on Ctrl+Shift+Q.

Launches ccwork in a sandbox, focuses it, injects Ctrl+Shift+Q, then
reads the sandboxed ``settings.toml`` and asserts that
``[window].geometry`` contains a non-empty base64 string. End-to-end
proof that:

  - The Ctrl+Shift+Q binding still fires.
  - `closeEvent` reaches `_persist_window_state` past the (absent)
    working-session prompt.
  - `saveGeometry()` round-trips through `_window_to_toml` and lands
    on disk in the expected schema.
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

XK_Control_L = 0xffe3
XK_Shift_L = 0xffe1
XK_q = 0x0071


def send_ctrl_shift_q(dpy) -> None:
    kc_c = _x11.XKeysymToKeycode(dpy, ctypes.c_ulong(XK_Control_L))
    kc_s = _x11.XKeysymToKeycode(dpy, ctypes.c_ulong(XK_Shift_L))
    kc_q = _x11.XKeysymToKeycode(dpy, ctypes.c_ulong(XK_q))
    _xtst.XTestFakeKeyEvent(dpy, kc_c, 1, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc_s, 1, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc_q, 1, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc_q, 0, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc_s, 0, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc_c, 0, 0)
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
    sandbox = Path(tempfile.mkdtemp(prefix="ccwork-geom-"))
    cfg = sandbox / "config"
    cfg.mkdir()
    log_path = sandbox / "ccwork.log"
    settings_path = cfg / "ccwork" / "settings.toml"

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
    print(f"ccwork pid: {proc.pid}, sandbox: {sandbox}")

    try:
        # Wait for startup.
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if "global keys:" in (log_path.read_text(errors="replace") if log_path.exists() else ""):
                break
            time.sleep(0.1)
        else:
            print("FAIL: ccwork did not finish startup")
            return 1
        time.sleep(0.5)
        focus_ccwork()
        time.sleep(0.6)

        # Send Ctrl+Shift+Q.
        dpy = _x11.XOpenDisplay(None)
        if not dpy:
            print("FAIL: no $DISPLAY")
            return 1
        send_ctrl_shift_q(dpy)

        # Wait for clean exit.
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("FAIL: ccwork did not exit after Ctrl+Shift+Q")
            return 2

        # Check settings.toml for [window] geometry.
        if not settings_path.exists():
            print(f"FAIL: {settings_path} not written")
            return 3
        text = settings_path.read_text()
        if "[window]" not in text:
            print("FAIL: [window] section missing")
            print("---settings.toml---")
            print(text)
            return 4
        # The geometry value should be non-empty after a clean quit.
        in_window = False
        geom_value = None
        for line in text.splitlines():
            if line.strip() == "[window]":
                in_window = True
                continue
            if in_window and line.startswith("["):
                break
            if in_window and line.strip().startswith("geometry"):
                geom_value = line.split("=", 1)[1].strip().strip('"')
        if not geom_value:
            print("FAIL: geometry value empty (expected base64 blob)")
            print("---settings.toml---")
            print(text)
            return 5
        print(f"geometry blob (len={len(geom_value)}): {geom_value[:40]}...")
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
