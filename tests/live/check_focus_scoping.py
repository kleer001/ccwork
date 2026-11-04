"""Live verification that shortcuts are scoped to MainWindow focus.

The bug this guards against: a previous root-window XGrabKey caused
ccwork to intercept its shortcut combos *globally* — pressing
``Ctrl+Shift+P`` in Firefox popped ccwork's Preferences dialog. After
the 2026-05-13 fix, the grab is on MainWindow's own X window, so it
only activates when ccwork is in the focus chain.

Runs on its own Xvfb display (`harness.run_on_xvfb`).

Procedure:
  1. Launch ccwork.
  2. Focus another window (a plain xterm).
  3. Inject Ctrl+Shift+P via XTest.
  4. Assert: zero dispatch entries in the log (negative case).
  5. Focus ccwork.
  6. Inject Ctrl+Shift+P.
  7. Assert: one new dispatch entry (positive case).

If either assertion fails, the focus scoping regressed and shortcuts
are leaking outside ccwork's window again.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import harness

REPO = Path(__file__).resolve().parents[2]
OTHER_TITLE = "live-other-window"

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
XK_p = 0x0070
XK_q = 0x0071


def send_ctrl_shift(dpy, keysym):
    kc_c = _x11.XKeysymToKeycode(dpy, ctypes.c_ulong(XK_Control_L))
    kc_s = _x11.XKeysymToKeycode(dpy, ctypes.c_ulong(XK_Shift_L))
    kc_k = _x11.XKeysymToKeycode(dpy, ctypes.c_ulong(keysym))
    _xtst.XTestFakeKeyEvent(dpy, kc_c, 1, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc_s, 1, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc_k, 1, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc_k, 0, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc_s, 0, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc_c, 0, 0)
    _x11.XSync(dpy, 0)


def wmctrl_focus(window_title_substring: str) -> None:
    """Focus the first window whose title contains the substring.

    Used only for "focus *something else* that isn't ccwork." For
    focusing ccwork itself prefer harness.focus_ccwork() — substring
    matching on titles is unreliable because a shell prompt in the
    title often contains 'ccwork' as the cwd.
    """
    subprocess.run(["wmctrl", "-a", window_title_substring], check=False)


def count_dispatches(log_path: Path) -> int:
    try:
        return log_path.read_text(errors="replace").count("KeyGrabFilter DISPATCH")
    except FileNotFoundError:
        return 0


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="ccwork-focus-"))
    cfg = sandbox / "config"
    cfg.mkdir()
    log_path = harness.evidence_dir() / "ccwork.log"

    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(cfg)
    env["CCWORK_LOG"] = "INFO"

    # Before ccwork: a failure here leaves no ccwork running.
    other = harness.open_other_window(OTHER_TITLE)
    proc = subprocess.Popen(
        [str(REPO / ".venv/bin/python"), "-m", "src.main"],
        cwd=str(REPO),
        env=env,
        stdout=open(log_path, "wb"),
        stderr=subprocess.STDOUT,
    )
    print(f"pid={proc.pid} sandbox={sandbox}")

    try:
        # Wait for startup.
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if "global keys:" in (log_path.read_text(errors="replace") if log_path.exists() else ""):
                break
            time.sleep(0.1)
        else:
            print("FAIL: startup")
            return 1
        time.sleep(0.5)

        dpy = _x11.XOpenDisplay(None)

        # ── NEGATIVE: focus the other xterm, inject Ctrl+Shift+P, expect 0 dispatch ──
        wmctrl_focus(OTHER_TITLE)
        time.sleep(0.6)
        before_neg = count_dispatches(log_path)
        send_ctrl_shift(dpy, XK_p)
        time.sleep(0.6)
        after_neg = count_dispatches(log_path)
        neg_pass = after_neg == before_neg
        print(f"  ccwork unfocused + Ctrl+Shift+P → dispatches: "
              f"{before_neg} → {after_neg}  {'OK' if neg_pass else 'FAIL'}")

        # ── POSITIVE: focus ccwork, inject Ctrl+Shift+P, expect dispatch ──
        harness.focus_ccwork()
        time.sleep(0.8)
        before_pos = count_dispatches(log_path)
        send_ctrl_shift(dpy, XK_p)
        time.sleep(0.6)
        after_pos = count_dispatches(log_path)
        pos_pass = after_pos > before_pos
        print(f"  ccwork focused + Ctrl+Shift+P → dispatches: "
              f"{before_pos} → {after_pos}  {'OK' if pos_pass else 'FAIL'}")

        # Clean exit.
        send_ctrl_shift(dpy, XK_q)
        time.sleep(0.6)

        result = neg_pass and pos_pass
        print(f"\nresult: {'PASS' if result else 'FAIL'}")
        return 0 if result else 2

    finally:
        other.kill()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
