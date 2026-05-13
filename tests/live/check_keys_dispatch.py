"""Live verification that the full shortcut surface dispatches.

Launches ccwork in a sandbox, focuses it, then injects each of the
five canonical shortcut combos via libXtst and asserts that each
produces a ``KeyGrabFilter DISPATCH`` log line (and, where applicable,
a visible dialog window). Modal dialogs are dismissed with `Esc` and
ccwork is re-focused between steps because KDE Plasma doesn't always
restore focus to the parent cleanly after a modal closes.

Use as a smoke check after touching the bindings table in
``MainWindow._install_global_keys`` — it covers the common breakage
shapes (modifier mask wrong, callback signature mismatch, modal
focus issues) in one run.
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


# ─── libXtst keystroke injection ───────────────────────────────────────────

_x11 = ctypes.CDLL("libX11.so.6", use_errno=True)
_xtst = ctypes.CDLL("libXtst.so.6", use_errno=True)

_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
_x11.XOpenDisplay.restype = ctypes.c_void_p
_x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_x11.XKeysymToKeycode.restype = ctypes.c_ubyte
_x11.XFlush.argtypes = [ctypes.c_void_p]
_x11.XFlush.restype = ctypes.c_int
_x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
_x11.XSync.restype = ctypes.c_int
_x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
_x11.XCloseDisplay.restype = ctypes.c_int

_xtst.XTestFakeKeyEvent.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong,
]
_xtst.XTestFakeKeyEvent.restype = ctypes.c_int

XK_Control_L = 0xffe3
XK_Shift_L = 0xffe1
XK_Tab = 0xff09
XK_Escape = 0xff1b
XK_p = 0x0070
XK_q = 0x0071
XK_o = 0x006f
XK_1 = 0x0031


def open_display() -> ctypes.c_void_p:
    dpy = _x11.XOpenDisplay(None)
    if not dpy:
        raise RuntimeError("XOpenDisplay returned NULL — $DISPLAY unset?")
    return dpy


def keycode(dpy, keysym: int) -> int:
    return int(_x11.XKeysymToKeycode(dpy, ctypes.c_ulong(keysym)))


def send_combo(dpy, keysym: int, with_ctrl=True, with_shift=False) -> None:
    """Press modifiers + key, then release in reverse order."""
    kc_key = keycode(dpy, keysym)
    kc_ctrl = keycode(dpy, XK_Control_L)
    kc_shift = keycode(dpy, XK_Shift_L)
    if with_ctrl:
        _xtst.XTestFakeKeyEvent(dpy, kc_ctrl, 1, 0)
    if with_shift:
        _xtst.XTestFakeKeyEvent(dpy, kc_shift, 1, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc_key, 1, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc_key, 0, 0)
    if with_shift:
        _xtst.XTestFakeKeyEvent(dpy, kc_shift, 0, 0)
    if with_ctrl:
        _xtst.XTestFakeKeyEvent(dpy, kc_ctrl, 0, 0)
    _x11.XSync(dpy, 0)


def send_bare(dpy, keysym: int) -> None:
    """Press and release a key with no modifiers (used for Escape)."""
    kc = keycode(dpy, keysym)
    _xtst.XTestFakeKeyEvent(dpy, kc, 1, 0)
    _xtst.XTestFakeKeyEvent(dpy, kc, 0, 0)
    _x11.XSync(dpy, 0)


# ─── log + window helpers ──────────────────────────────────────────────────

def wait_for(log_path: Path, needle: str, timeout: float = 6.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if needle in log_path.read_text(errors="replace"):
                return True
        except FileNotFoundError:
            pass
        time.sleep(0.1)
    return False


def count_dispatches(log_path: Path) -> int:
    try:
        return log_path.read_text(errors="replace").count("KeyGrabFilter DISPATCH")
    except FileNotFoundError:
        return 0


def wmctrl_windows() -> list[str]:
    try:
        out = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=2)
        return [l for l in out.stdout.splitlines() if l.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def focus_ccwork() -> bool:
    """Focus ccwork by WM_CLASS (`main.py.ccwork`) — substring matching on
    titles is unreliable here because Konsole's prompt often contains
    'ccwork' as the cwd. Required since MainWindow-scoped grabs only
    activate when ccwork is in the focus chain.
    """
    out = subprocess.run(["wmctrl", "-lx"], capture_output=True, text=True)
    for line in out.stdout.splitlines():
        if "main.py.ccwork" in line:
            wid = line.split()[0]
            subprocess.run(["wmctrl", "-ia", wid], check=False)
            return True
    return False


# ─── main ──────────────────────────────────────────────────────────────────

def main() -> int:
    if not os.environ.get("DISPLAY"):
        print("FAIL: $DISPLAY unset, cannot run live test")
        return 1

    sandbox = Path(tempfile.mkdtemp(prefix="ccwork-keytest-"))
    cfg = sandbox / "config"
    cfg.mkdir()
    log_path = sandbox / "ccwork.log"

    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(cfg)
    env["CCWORK_LOG"] = "INFO"

    print(f"sandbox: {sandbox}")
    proc = subprocess.Popen(
        [str(REPO / ".venv/bin/python"), "-m", "src.main"],
        cwd=str(REPO),
        env=env,
        stdout=open(log_path, "wb"),
        stderr=subprocess.STDOUT,
    )
    print(f"ccwork pid: {proc.pid}")

    try:
        if not wait_for(log_path, "global keys:", timeout=10.0):
            print("FAIL: ccwork did not finish startup within 10 s")
            return 2
        line = next(l for l in log_path.read_text().splitlines() if "global keys:" in l)
        print(f"  startup: {line.strip()}")
        if "shortcuts on MainWindow=" not in line:
            print("FAIL: grabs were skipped (platform != xcb?)")
            return 3

        time.sleep(0.5)
        focus_ccwork()
        time.sleep(0.6)
        dpy = open_display()

        # Ctrl+Shift+P → Preferences dialog
        before = count_dispatches(log_path)
        send_combo(dpy, XK_p, with_ctrl=True, with_shift=True)
        time.sleep(0.6)
        prefs_dispatch = count_dispatches(log_path) > before
        windows = wmctrl_windows()
        prefs_visible = any("preferences" in w.lower() for w in windows)
        print(f"  Ctrl+Shift+P  dispatch={prefs_dispatch}  prefs_window={prefs_visible}")
        if not prefs_dispatch:
            print(f"  windows: {windows}")
            print("FAIL: Ctrl+Shift+P did not dispatch")
            return 4

        send_bare(dpy, XK_Escape)
        time.sleep(0.3)
        focus_ccwork()
        time.sleep(0.5)

        # Ctrl+Tab — cycle repo (no-op with 0 repos but must DISPATCH)
        d0 = count_dispatches(log_path)
        send_combo(dpy, XK_Tab, with_ctrl=True, with_shift=False)
        time.sleep(0.3)
        tab_dispatch = count_dispatches(log_path) > d0
        print(f"  Ctrl+Tab      dispatch={tab_dispatch}")

        # Ctrl+Shift+1 — row jump
        d1 = count_dispatches(log_path)
        send_combo(dpy, XK_1, with_ctrl=True, with_shift=True)
        time.sleep(0.3)
        jump_dispatch = count_dispatches(log_path) > d1
        print(f"  Ctrl+Shift+1  dispatch={jump_dispatch}")

        # Ctrl+Shift+Tab — cycle prev
        d2 = count_dispatches(log_path)
        send_combo(dpy, XK_Tab, with_ctrl=True, with_shift=True)
        time.sleep(0.3)
        backtab_dispatch = count_dispatches(log_path) > d2
        print(f"  Ctrl+Shift+Tab dispatch={backtab_dispatch}")

        # Ctrl+Shift+O — Add Repo dialog
        d3 = count_dispatches(log_path)
        send_combo(dpy, XK_o, with_ctrl=True, with_shift=True)
        time.sleep(0.5)
        addrepo_dispatch = count_dispatches(log_path) > d3
        windows2 = wmctrl_windows()
        add_visible = any("Add repo" in w for w in windows2)
        print(f"  Ctrl+Shift+O  dispatch={addrepo_dispatch}  dialog_window={add_visible}")

        send_bare(dpy, XK_Escape)
        time.sleep(0.3)
        focus_ccwork()
        time.sleep(0.3)

        _x11.XCloseDisplay(dpy)

        all_ok = (
            prefs_dispatch and tab_dispatch and jump_dispatch
            and backtab_dispatch and addrepo_dispatch
        )
        print(f"\nresult: {'PASS' if all_ok else 'FAIL'}")
        return 0 if all_ok else 5

    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        print(f"log preserved at {log_path}")


if __name__ == "__main__":
    sys.exit(main())
