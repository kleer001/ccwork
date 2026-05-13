"""Diagnostic XGrabKey probe — minimal Qt-free reproducer.

Use this when investigating whether the XTest → XGrabKey → event-delivery
path itself is healthy, isolated from ccwork's Qt event filter. Was the
load-bearing diagnostic that surfaced the original "events arrive on the
wrong Display* connection" bug during the 2026-05-13 keybinding rework:
the probe received the synthetic press while ccwork (using a separate
XOpenDisplay) did not — proving the bug was in ccwork's connection
choice, not in XTest or grab activation.

How to use:

    # Terminal 1: run the probe
    .venv/bin/python tests/live/probe_xgrabkey.py
    # Terminal 2: inject (or just press Ctrl+Shift+P manually)
    python -c "
    import ctypes
    x = ctypes.CDLL('libX11.so.6'); xt = ctypes.CDLL('libXtst.so.6')
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XKeysymToKeycode.restype = ctypes.c_ubyte
    xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    dpy = x.XOpenDisplay(None)
    for ks in (0xffe3, 0xffe1, 0x70):  # Ctrl_L, Shift_L, p
        kc = x.XKeysymToKeycode(dpy, ctypes.c_ulong(ks))
        xt.XTestFakeKeyEvent(dpy, kc, 1, 0)
    for ks in (0x70, 0xffe1, 0xffe3):
        kc = x.XKeysymToKeycode(dpy, ctypes.c_ulong(ks))
        xt.XTestFakeKeyEvent(dpy, kc, 0, 0)
    x.XSync(dpy, 0)"

If the probe prints a KeyPress line, X-side is healthy. If not, look
at libXtst version, XTEST extension presence, or whether another
client has the same combo grabbed.

The probe grabs on **root** (not MainWindow like ccwork does) because
the goal is to test that XTest synthesized presses can reach a grab
**at all**, not to test ccwork's specific scoping.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import POINTER, byref, c_int, c_uint, c_ulong, c_ubyte, c_void_p


_x11 = ctypes.CDLL("libX11.so.6", use_errno=True)


# ─── X types and constants ─────────────────────────────────────────────────

Display = c_void_p
Window = c_ulong
XID = c_ulong

ShiftMask = 1 << 0
LockMask = 1 << 1
ControlMask = 1 << 2
Mod2Mask = 1 << 4

GrabModeAsync = 1
KeyPressMask = 1 << 0

XK_p = 0x0070


class XErrorEvent(ctypes.Structure):
    _fields_ = [
        ("type", c_int),
        ("display", Display),
        ("serial", c_ulong),
        ("error_code", c_ubyte),
        ("request_code", c_ubyte),
        ("minor_code", c_ubyte),
        ("resourceid", XID),
    ]


class XKeyEvent(ctypes.Structure):
    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", Display),
        ("window", Window),
        ("root", Window),
        ("subwindow", Window),
        ("time", c_ulong),
        ("x", c_int),
        ("y", c_int),
        ("x_root", c_int),
        ("y_root", c_int),
        ("state", c_uint),
        ("keycode", c_uint),
        ("same_screen", c_int),
    ]


class XAnyEvent(ctypes.Structure):
    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", Display),
        ("window", Window),
    ]


class XEvent(ctypes.Union):
    _fields_ = [
        ("type", c_int),
        ("xany", XAnyEvent),
        ("xkey", XKeyEvent),
        ("pad", c_ulong * 24),
    ]


# ─── Bindings ──────────────────────────────────────────────────────────────

_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
_x11.XOpenDisplay.restype = Display
_x11.XDefaultRootWindow.argtypes = [Display]
_x11.XDefaultRootWindow.restype = Window
_x11.XKeysymToKeycode.argtypes = [Display, c_ulong]
_x11.XKeysymToKeycode.restype = c_ubyte
_x11.XGrabKey.argtypes = [Display, c_int, c_uint, Window, c_int, c_int, c_int]
_x11.XGrabKey.restype = c_int
_x11.XSync.argtypes = [Display, c_int]
_x11.XSync.restype = c_int
_x11.XFlush.argtypes = [Display]
_x11.XFlush.restype = c_int
_x11.XNextEvent.argtypes = [Display, POINTER(XEvent)]
_x11.XNextEvent.restype = c_int

ErrorHandler = ctypes.CFUNCTYPE(c_int, Display, POINTER(XErrorEvent))


def _on_x_error(dpy, ev_p):
    ev = ev_p.contents
    print(f"  X ERROR: code={ev.error_code} request={ev.request_code} "
          f"resourceid=0x{ev.resourceid:x}", flush=True)
    return 0


_error_handler = ErrorHandler(_on_x_error)
_x11.XSetErrorHandler.argtypes = [ErrorHandler]
_x11.XSetErrorHandler.restype = ErrorHandler


def main() -> int:
    if not os.environ.get("DISPLAY"):
        print("FAIL: $DISPLAY unset")
        return 1
    _x11.XSetErrorHandler(_error_handler)
    dpy = _x11.XOpenDisplay(None)
    if not dpy:
        print("FAIL: XOpenDisplay")
        return 1
    root = _x11.XDefaultRootWindow(dpy)
    kc = int(_x11.XKeysymToKeycode(dpy, c_ulong(XK_p)))
    print(f"display open, root=0x{root:x}, p keycode={kc}", flush=True)

    # Grab Ctrl+Shift+P on root with the four lock-variant fan-out.
    for lock in (0, LockMask, Mod2Mask, LockMask | Mod2Mask):
        _x11.XGrabKey(
            dpy,
            c_int(kc),
            c_uint(ControlMask | ShiftMask | lock),
            Window(root),
            c_int(1),                # owner_events=True
            c_int(GrabModeAsync),    # pointer
            c_int(GrabModeAsync),    # keyboard
        )
    _x11.XSync(dpy, 0)               # flush + surface any BadAccess
    print("grab installed — waiting for Ctrl+Shift+P presses (Ctrl+C to quit)", flush=True)

    ev = XEvent()
    while True:
        _x11.XNextEvent(dpy, byref(ev))
        if ev.type == 2:  # KeyPress
            k = ev.xkey
            print(f"  KeyPress  keycode={k.keycode}  state=0x{k.state:x}  "
                  f"window=0x{k.window:x}", flush=True)
        elif ev.type == 3:  # KeyRelease
            k = ev.xkey
            print(f"  KeyRel    keycode={k.keycode}  state=0x{k.state:x}", flush=True)
        else:
            print(f"  type={ev.type}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
