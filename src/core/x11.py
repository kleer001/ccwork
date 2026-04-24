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

    _x11 = lib
    return lib


class XDisplay:
    """RAII wrapper for a libX11 Display handle."""

    def __init__(self, name: bytes | None = None) -> None:
        self._lib = _lib()
        self._dpy = self._lib.XOpenDisplay(name)
        if not self._dpy:
            raise RuntimeError("XOpenDisplay returned NULL — is $DISPLAY set?")

    def close(self) -> None:
        if self._dpy:
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
