"""Thin ctypes wrapper over libX11 for window geometry operations.

We only need: open display, query child windows of a window, resize a window,
flush. All other X calls go through Qt.

If libX11 is unavailable (`load()` raises), callers should treat this as a
fatal environment error — embedding xterm is Linux/X11-only by design.
"""

from __future__ import annotations

import ctypes
from ctypes import c_int, c_uint, c_ulong, c_void_p, POINTER, byref
from typing import Optional


Display = c_void_p
Window = c_ulong
Status = c_int
KeyCode = ctypes.c_ubyte
KeySym = c_ulong

# X11 event masks / modifiers we need. Values are fixed by the X protocol.
KeyPressMask = 1 << 0
ButtonPressMask = 1 << 2
ShiftMask = 1 << 0
LockMask = 1 << 1       # CapsLock
ControlMask = 1 << 2
Mod1Mask = 1 << 3       # Alt on most layouts
Mod2Mask = 1 << 4       # NumLock on most layouts
Mod4Mask = 1 << 6       # Super / Meta on most layouts
GrabModeAsync = 1
RevertToParent = 2
CurrentTime = 0

# Mouse buttons — wheel-up / wheel-down on X11.
Button4 = 4
Button5 = 5

# Keysyms (from /usr/include/X11/keysymdef.h). ASCII keysyms are just the
# ASCII code, so XK_p == ord('p'); we name the ones we actually grab.
# XK_1 starts the digit run — XK_1 + n - 1 gives the nth digit's keysym.
XK_equal = 0x003d       # '='
XK_plus = 0x002b        # '+'  (only reachable without Shift on some layouts)
XK_minus = 0x002d       # '-'
XK_0 = 0x0030           # '0'
XK_1 = 0x0031
XK_o = 0x006f
XK_p = 0x0070
XK_q = 0x0071
XK_Tab = 0xff09         # Tab
XK_F1 = 0xffbe          # F1   (primary keyboard-shortcuts trigger)


_x11: Optional[ctypes.CDLL] = None


def _lib() -> ctypes.CDLL:
    global _x11
    if _x11 is not None:
        return _x11
    lib = ctypes.CDLL("libX11.so.6", use_errno=True)

    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XOpenDisplay.restype = Display
    lib.XCloseDisplay.argtypes = [Display]
    lib.XCloseDisplay.restype = c_int
    lib.XFlush.argtypes = [Display]
    lib.XFlush.restype = c_int
    lib.XSync.argtypes = [Display, c_int]
    lib.XSync.restype = c_int
    lib.XQueryTree.argtypes = [
        Display, Window,
        POINTER(Window), POINTER(Window),
        POINTER(POINTER(Window)), POINTER(c_uint),
    ]
    lib.XQueryTree.restype = Status
    lib.XFree.argtypes = [c_void_p]
    lib.XFree.restype = c_int
    lib.XResizeWindow.argtypes = [Display, Window, c_uint, c_uint]
    lib.XResizeWindow.restype = c_int
    lib.XMoveResizeWindow.argtypes = [Display, Window, c_int, c_int, c_uint, c_uint]
    lib.XMoveResizeWindow.restype = c_int
    lib.XKeysymToKeycode.argtypes = [Display, KeySym]
    lib.XKeysymToKeycode.restype = KeyCode
    lib.XGrabKey.argtypes = [
        Display, c_int, c_uint, Window, c_int, c_int, c_int,
    ]
    lib.XGrabKey.restype = c_int
    lib.XUngrabKey.argtypes = [Display, c_int, c_uint, Window]
    lib.XUngrabKey.restype = c_int
    lib.XGrabButton.argtypes = [
        Display, c_uint, c_uint, Window, c_int, c_uint, c_int, c_int,
        Window, c_ulong,
    ]
    lib.XGrabButton.restype = c_int
    lib.XUngrabButton.argtypes = [Display, c_uint, c_uint, Window]
    lib.XUngrabButton.restype = c_int
    lib.XSetInputFocus.argtypes = [Display, Window, c_int, c_ulong]
    lib.XSetInputFocus.restype = c_int
    lib.XDefaultRootWindow.argtypes = [Display]
    lib.XDefaultRootWindow.restype = Window

    _x11 = lib
    return lib


# The four lock-key variants we must grab alongside ControlMask so the grab
# still triggers when NumLock/CapsLock happen to be on. X11 reports lock
# state as part of the modifier mask, so a naive ControlMask-only grab only
# fires when both locks are off.
_LOCK_VARIANTS = (0, LockMask, Mod2Mask, LockMask | Mod2Mask)


class XDisplay:
    """RAII wrapper for a libX11 Display handle.

    Default construction opens a fresh X connection. Use ``attach()`` to
    wrap a pre-existing display pointer (e.g. Qt's own xcb connection's
    Display*) — the wrapper then does **not** close it on cleanup, which
    is mandatory when the pointer is owned by another subsystem.

    Why this matters for grabs: ``XGrabKey`` delivers matched events to
    the **grabber's connection**, not to every client that happens to
    listen on the grab window. A grab installed on a separate X
    connection is invisible to Qt's event loop — Qt's
    ``QAbstractNativeEventFilter`` only ever sees events on Qt's own
    connection. So passive grabs that need to fire Qt callbacks must be
    installed on Qt's display, accessed via
    ``QNativeInterface::QX11Application::display()``.
    """

    def __init__(self, name: bytes | None = None) -> None:
        self._lib = _lib()
        self._dpy = self._lib.XOpenDisplay(name)
        self._owned = True
        if not self._dpy:
            raise RuntimeError("XOpenDisplay returned NULL — is $DISPLAY set?")

    @classmethod
    def attach(cls, handle: int) -> "XDisplay":
        """Wrap a pre-existing ``Display*`` (as raw int). The caller retains
        ownership; ``close()`` is a no-op on attached instances."""
        if not handle:
            raise ValueError("attach() requires a non-null Display handle")
        obj = cls.__new__(cls)
        obj._lib = _lib()
        obj._dpy = c_void_p(handle)
        obj._owned = False
        return obj

    def close(self) -> None:
        if self._dpy and self._owned:
            self._lib.XCloseDisplay(self._dpy)
        self._dpy = None

    def __del__(self) -> None:  # pragma: no cover
        # Interpreter shutdown may null out self._lib / self._dpy before __del__
        # runs; guard everything so we don't spam stderr with AttributeError.
        try:
            if getattr(self, "_lib", None) is not None and getattr(self, "_dpy", None):
                self.close()
        except Exception:
            pass

    @property
    def handle(self) -> Display:
        return self._dpy

    def flush(self) -> None:
        self._lib.XFlush(self._dpy)

    def sync(self, discard: bool = False) -> None:
        self._lib.XSync(self._dpy, 1 if discard else 0)

    def query_children(self, parent: int) -> list[int]:
        """Return the IDs of all direct X children of `parent`."""
        root = Window()
        dummy_parent = Window()
        children_ptr = POINTER(Window)()
        nchildren = c_uint()
        status = self._lib.XQueryTree(
            self._dpy, Window(parent),
            byref(root), byref(dummy_parent),
            byref(children_ptr), byref(nchildren),
        )
        if status == 0:
            return []
        try:
            return [int(children_ptr[i]) for i in range(nchildren.value)]
        finally:
            if children_ptr:
                self._lib.XFree(children_ptr)

    def resize_window(self, win: int, width: int, height: int) -> None:
        # X rejects 0 or negative dimensions; clamp silently.
        w = max(1, int(width))
        h = max(1, int(height))
        self._lib.XResizeWindow(self._dpy, Window(win), c_uint(w), c_uint(h))

    def move_resize_window(self, win: int, x: int, y: int, width: int, height: int) -> None:
        w = max(1, int(width))
        h = max(1, int(height))
        self._lib.XMoveResizeWindow(
            self._dpy, Window(win), c_int(int(x)), c_int(int(y)), c_uint(w), c_uint(h)
        )

    def keysym_to_keycode(self, keysym: int) -> int:
        return int(self._lib.XKeysymToKeycode(self._dpy, KeySym(keysym)))

    def grab_key(self, win: int, keysym: int, modifiers: int) -> None:
        """Passive-grab `keysym`+`modifiers` on `win`. Fans out the grab
        across lock-key combinations so it fires with NumLock or CapsLock on.
        The grab routes matching KeyPress events to the owner of `win`
        regardless of which descendant currently holds focus — which is how
        we catch zoom shortcuts while an xterm child has the keyboard.
        """
        code = self.keysym_to_keycode(keysym)
        if code == 0:
            return  # keysym unmapped on this server — silently skip
        for extra in _LOCK_VARIANTS:
            self._lib.XGrabKey(
                self._dpy,
                c_int(code),
                c_uint(modifiers | extra),
                Window(win),
                c_int(1),                 # owner_events: True — other
                                          # windows still see unrelated keys
                c_int(GrabModeAsync),     # pointer mode
                c_int(GrabModeAsync),     # keyboard mode
            )

    def ungrab_key(self, win: int, keysym: int, modifiers: int) -> None:
        code = self.keysym_to_keycode(keysym)
        if code == 0:
            return
        for extra in _LOCK_VARIANTS:
            self._lib.XUngrabKey(self._dpy, c_int(code), c_uint(modifiers | extra), Window(win))

    def grab_button(self, win: int, button: int, modifiers: int) -> None:
        """Passive-grab `button`+`modifiers` on `win`. Same lock-variant fan
        out as grab_key. Used for Ctrl+scroll-wheel."""
        for extra in _LOCK_VARIANTS:
            self._lib.XGrabButton(
                self._dpy,
                c_uint(button),
                c_uint(modifiers | extra),
                Window(win),
                c_int(1),                    # owner_events
                c_uint(ButtonPressMask),
                c_int(GrabModeAsync),        # pointer mode
                c_int(GrabModeAsync),        # keyboard mode
                Window(0),                   # confine_to: None
                c_ulong(0),                  # cursor: None
            )

    def ungrab_button(self, win: int, button: int, modifiers: int) -> None:
        for extra in _LOCK_VARIANTS:
            self._lib.XUngrabButton(self._dpy, c_uint(button), c_uint(modifiers | extra), Window(win))

    def set_input_focus(self, win: int) -> None:
        """XSetInputFocus(win, RevertToParent, CurrentTime). No-op if win==0."""
        if not win:
            return
        self._lib.XSetInputFocus(
            self._dpy, Window(win), c_int(RevertToParent), c_ulong(CurrentTime)
        )
        self._lib.XFlush(self._dpy)

    def default_root_window(self) -> int:
        """The screen-default root window. Used as the grab_window for
        application-global passive grabs that must fire regardless of which
        window currently has focus."""
        return int(self._lib.XDefaultRootWindow(self._dpy))
