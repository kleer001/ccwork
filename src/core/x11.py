"""Thin ctypes wrapper over libX11 for the X calls that Qt does not make.

We only need: open a display or wrap Qt's own (`XDisplay.qt`), query child
windows of a window, read a window's map state, resize a window, select its
events, set the input focus, flush, key and button grabs, and XTEST key
injection (libXtst) for typing into the embedded xterm. `xcb_event` reads an
xcb event that Qt passes to a native event filter. All other X calls go
through Qt.

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
StructureNotifyMask = 1 << 17
IsUnmapped = 0          # XWindowAttributes.map_state
ShiftMask = 1 << 0
LockMask = 1 << 1       # CapsLock
ControlMask = 1 << 2
Mod1Mask = 1 << 3       # Alt on most layouts
Mod2Mask = 1 << 4       # NumLock on most layouts
Mod4Mask = 1 << 6       # Super / Meta on most layouts
GrabModeAsync = 1
RevertToParent = 2
CurrentTime = 0

# An xcb event's type is the lower 7 bits of `response_type`; bit 7 marks a
# synthetic (SendEvent) event, which counts as the same type.
XCB_RESPONSE_TYPE_MASK = 0x7F
XCB_EVENT_TYPE = b"xcb_generic_event_t"  # Qt's native event type on xcb
XCB_KEY_PRESS = 2
XCB_MAP_NOTIFY = 19

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
XK_c = 0x0063
XK_o = 0x006f
XK_p = 0x0070
XK_q = 0x0071
XK_z = 0x007a
XK_Tab = 0xff09         # Tab
XK_F1 = 0xffbe          # F1   (primary keyboard-shortcuts trigger)
XK_v = 0x0076
XK_Shift_L = 0xffe1
XK_Control_L = 0xffe3


class XWindowAttributes(ctypes.Structure):
    """Layout of `XWindowAttributes` from Xlib.h."""

    _fields_ = [
        ("x", c_int), ("y", c_int), ("width", c_int), ("height", c_int),
        ("border_width", c_int), ("depth", c_int), ("visual", c_void_p),
        ("root", Window), ("class_", c_int), ("bit_gravity", c_int),
        ("win_gravity", c_int), ("backing_store", c_int),
        ("backing_planes", c_ulong), ("backing_pixel", c_ulong),
        ("save_under", c_int), ("colormap", c_ulong), ("map_installed", c_int),
        ("map_state", c_int), ("all_event_masks", ctypes.c_long),
        ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", c_int), ("screen", c_void_p),
    ]


def xcb_event(event_type, message, layout: type[ctypes.Structure], code: int):
    """The xcb event of type `code` that Qt passes to a native event filter
    (`event_type`, `message`), read as the ctypes `layout`; None for an event
    of another type."""
    if bytes(event_type) != XCB_EVENT_TYPE:
        return None
    ev = layout.from_address(int(message))
    return ev if ev.response_type & XCB_RESPONSE_TYPE_MASK == code else None


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
    lib.XSelectInput.argtypes = [Display, Window, ctypes.c_long]
    lib.XSelectInput.restype = c_int
    lib.XGetWindowAttributes.argtypes = [Display, Window, POINTER(XWindowAttributes)]
    lib.XGetWindowAttributes.restype = Status
    lib.XDefaultRootWindow.argtypes = [Display]
    lib.XDefaultRootWindow.restype = Window
    lib.XkbKeycodeToKeysym.argtypes = [Display, KeyCode, c_uint, c_uint]
    lib.XkbKeycodeToKeysym.restype = KeySym

    _x11 = lib
    return lib


_xtst: Optional[ctypes.CDLL] = None


def _tst() -> ctypes.CDLL:
    """libXtst, for XTestFakeKeyEvent. Loaded on first use."""
    global _xtst
    if _xtst is None:
        lib = ctypes.CDLL("libXtst.so.6")
        lib.XTestFakeKeyEvent.argtypes = [Display, c_uint, c_int, c_ulong]
        lib.XTestFakeKeyEvent.restype = c_int
        _xtst = lib
    return _xtst


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
    def qt(cls) -> "XDisplay":
        """Qt's own X connection. A grab or an event selection on it sends
        its events to Qt's native event filters. On xcb, PySide6 >= 6.6 gives
        a non-null Display*, so a failure here is loud."""
        from PySide6.QtGui import QGuiApplication
        return cls.attach(int(QGuiApplication.instance().nativeInterface().display()))

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

    def select_input(self, win: int, mask: int) -> None:
        """XSelectInput: this connection's event mask on `win`."""
        self._lib.XSelectInput(self._dpy, Window(win), mask)
        self._lib.XFlush(self._dpy)

    def map_state(self, win: int) -> int:
        """`map_state` of `win` (IsUnmapped, IsUnviewable, IsViewable);
        IsUnmapped when the window is gone."""
        attrs = XWindowAttributes()
        if self._lib.XGetWindowAttributes(self._dpy, Window(win), byref(attrs)) == 0:
            return IsUnmapped
        return attrs.map_state

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

    def _fake_key(self, keycode: int, press: bool) -> None:
        _tst().XTestFakeKeyEvent(self._dpy, c_uint(keycode), c_int(int(press)), c_ulong(0))

    def press_combo(self, modifier_keysyms: tuple[int, ...], keysym: int) -> None:
        """Inject a key chord (e.g. Ctrl+Shift+V) through XTEST. It reaches
        whichever window holds X input focus, like a real keypress."""
        mods = [int(self.keysym_to_keycode(m)) for m in modifier_keysyms]
        key = int(self.keysym_to_keycode(keysym))
        for kc in mods:
            self._fake_key(kc, True)
        self._fake_key(key, True)
        self._fake_key(key, False)
        for kc in reversed(mods):
            self._fake_key(kc, False)
        self._lib.XFlush(self._dpy)

    def type_ascii(self, text: str) -> None:
        """Type printable ASCII through XTEST into the focused window. Uses
        Shift for characters on a key's second level. Raises ValueError for a
        character the keyboard map cannot produce."""
        shift = int(self.keysym_to_keycode(XK_Shift_L))
        for ch in text:
            keysym = ord(ch)   # printable ASCII keysyms equal the ASCII code
            if not 0x20 <= keysym <= 0x7e:
                raise ValueError(f"type_ascii: {ch!r} is not printable ASCII")
            kc = int(self.keysym_to_keycode(keysym))
            if kc == 0:
                raise ValueError(f"type_ascii: no key produces {ch!r}")
            if self._lib.XkbKeycodeToKeysym(self._dpy, KeyCode(kc), 0, 0) == keysym:
                self._fake_key(kc, True)
                self._fake_key(kc, False)
            elif self._lib.XkbKeycodeToKeysym(self._dpy, KeyCode(kc), 0, 1) == keysym:
                self._fake_key(shift, True)
                self._fake_key(kc, True)
                self._fake_key(kc, False)
                self._fake_key(shift, False)
            else:
                raise ValueError(f"type_ascii: {ch!r} needs a modifier other than Shift")
        self._lib.XFlush(self._dpy)

    def default_root_window(self) -> int:
        """The screen-default root window. Used as the grab_window for
        application-global passive grabs that must fire regardless of which
        window currently has focus."""
        return int(self._lib.XDefaultRootWindow(self._dpy))
