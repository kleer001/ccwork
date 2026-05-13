"""Native-event dispatch for our XGrabKey shortcuts.

Why this exists, in one paragraph: with the embedded xterm holding X
input focus, Qt's `keyPressEvent` never fires on the container — xterm
isn't a Qt widget, so there is no focus widget Qt would route the event
to. `XGrabKey(..., owner_events=True)` still causes the X server to
deliver the press into our process, but it arrives as a raw native
event (XCB_KEY_PRESS) with no Qt-side translation. The canonical way
real Qt apps catch these is `QAbstractNativeEventFilter` — same pattern
as Skycoder42/QHotkey and CopyQ's QxtGlobalShortcut. We match on
`(keycode, masked_state)` from the XCB struct, which also sidesteps the
`Ctrl+Shift+Tab → Key_Backtab` and `Ctrl+Shift+1 → Key_Exclam` artifacts
that bite QKeySequence comparisons in `QKeyEvent`-land.

Usage:
    filt = KeyGrabFilter(xdisplay)
    QApplication.instance().installNativeEventFilter(filt)
    filt.register(x11.XK_p, x11.ControlMask | x11.ShiftMask, open_prefs)
    filt.register(x11.XK_Tab, x11.ControlMask, lambda: cycle(+1))
    ...
"""

from __future__ import annotations

import ctypes
import logging
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter

from src.core import x11
from src.core.x11 import XDisplay


log = logging.getLogger(__name__)


# XCB key-press event op-code (lower 7 bits of response_type; bit 7 is the
# "send-event" flag for synthetic events, which we mask off).
_XCB_KEY_PRESS = 2
_RESPONSE_TYPE_MASK = 0x7f

# Modifier bits we care about for matching. LockMask (CapsLock) and
# Mod2Mask (NumLock) leak into `state` regardless of intent — strip them
# before comparing. Mod1Mask = Alt, Mod4Mask = Super; we leave them in
# so a Super-based shortcut can be wired without changing the mask.
# Exact same mask QHotkey (qhotkey_x11.cpp:69) and CopyQ
# (qxtglobalshortcut_x11.cpp:618) use.
_STATE_MASK = x11.ShiftMask | x11.ControlMask | x11.Mod1Mask | x11.Mod4Mask


class _XcbKeyPressEvent(ctypes.Structure):
    """Layout of `xcb_key_press_event_t` from xproto.h.

    We don't ship the xcb headers; the layout has been stable since
    libxcb-1.0 in 2006. If it ever changes we'll get nonsense `detail`
    values and notice immediately.
    """

    _fields_ = [
        ("response_type", ctypes.c_uint8),
        ("detail",        ctypes.c_uint8),   # keycode
        ("sequence",      ctypes.c_uint16),
        ("time",          ctypes.c_uint32),
        ("root",          ctypes.c_uint32),
        ("event",         ctypes.c_uint32),
        ("child",         ctypes.c_uint32),
        ("root_x",        ctypes.c_int16),
        ("root_y",        ctypes.c_int16),
        ("event_x",       ctypes.c_int16),
        ("event_y",       ctypes.c_int16),
        ("state",         ctypes.c_uint16),  # modifier mask
        ("same_screen",   ctypes.c_uint8),
        ("pad0",          ctypes.c_uint8),
    ]


class KeyGrabFilter(QAbstractNativeEventFilter):
    """Dispatches XCB_KEY_PRESS events to registered callbacks.

    Match is on `(keycode, state & _STATE_MASK)`. Register one entry per
    logical shortcut; the lock-key fan-out (NumLock/CapsLock variants)
    is the grab's responsibility — we mask the state on the way in so
    one entry covers all four lock states.
    """

    def __init__(self, xdisplay: XDisplay) -> None:
        super().__init__()
        self._xdisplay = xdisplay
        # {(keycode, masked_mods): callback}
        self._handlers: dict[tuple[int, int], Callable[[], None]] = {}

    # ── registration ──

    def register(self, keysym: int, mods: int, callback: Callable[[], None]) -> bool:
        """Map (keysym, mods) → callback. Returns False if the server has
        no keycode for that keysym (rare; unmapped on this layout)."""
        keycode = self._xdisplay.keysym_to_keycode(keysym)
        if keycode == 0:
            log.warning("KeyGrabFilter.register: keysym 0x%x has no keycode", keysym)
            return False
        key = (keycode, mods & _STATE_MASK)
        if key in self._handlers:
            log.warning("KeyGrabFilter: replacing handler for keycode=%d mods=0x%x",
                        keycode, mods)
        self._handlers[key] = callback
        log.info("KeyGrabFilter.register keycode=%d mods=0x%x (keysym=0x%x)",
                 keycode, mods & _STATE_MASK, keysym)
        return True

    # ── dispatch ──

    def nativeEventFilter(self, eventType, message):  # type: ignore[override]
        if bytes(eventType) != b"xcb_generic_event_t":
            return False, 0
        try:
            ptr = int(message)
        except (TypeError, ValueError):
            return False, 0
        ev = _XcbKeyPressEvent.from_address(ptr)
        # bit 7 of response_type is the SendEvent flag (synthetic); mask
        # it off before comparing so synthetic presses still dispatch.
        # XTestFakeKeyEvent presses arrive with the bit clear, so this is
        # belt-and-braces for any other source that synthesizes.
        rtype = ev.response_type & _RESPONSE_TYPE_MASK
        if rtype != _XCB_KEY_PRESS:
            return False, 0
        masked_mods = ev.state & _STATE_MASK
        key = (ev.detail, masked_mods)
        handler = self._handlers.get(key)
        if handler is None:
            # No log here — runs on every keystroke the user types into
            # xterm. Switch to log.debug if a missing-handler hunt is needed.
            return False, 0
        log.info("KeyGrabFilter DISPATCH keycode=%d mods=0x%x",
                 ev.detail, masked_mods)
        try:
            handler()
        except Exception:
            log.exception("KeyGrabFilter handler raised")
        # Returning True swallows the event so Qt's high-level translation
        # doesn't also fire (it wouldn't fire anyway for grabbed presses
        # when xterm has focus, but for sidebar-focus presses it would
        # double-deliver the keystroke).
        return True, 0


# ── main-window binding table ──


@dataclass(frozen=True)
class MainWindowSlots:
    """Callbacks the MainWindow binding table dispatches to.

    Frozen so the factory can't mutate it mid-build. Each slot maps to one
    or more rows in the binding table; adding a new shortcut means adding
    a field here, wiring it in `build_main_window_bindings`, and passing
    the bound method in `MainWindow._install_global_keys`.
    """

    open_preferences: Callable[[], None]
    add_repo:         Callable[[], None]
    quit:             Callable[[], None]
    open_shortcuts:   Callable[[], None]
    cycle_repo:       Callable[[int], None]   # +1 forward, -1 back
    zoom:             Callable[[int], None]   # +1 in, -1 out, 0 reset
    jump_to_row:      Callable[[int], None]   # 0-indexed: row 0..8


def build_main_window_bindings(
    slots: MainWindowSlots,
) -> list[tuple[int, int, Callable[[], None]]]:
    """Return the `(keysym, mods, callback)` table for MainWindow shortcuts.

    Centralizing the table here keeps MainWindow's install method to plain
    plumbing (platform check, attach to Qt's X display, install filter,
    grab + register loop). The lock-key fan-out (NumLock/CapsLock) is
    handled by `KeyGrabFilter`'s state mask, so each logical shortcut
    gets exactly one row.
    """
    Ctrl = x11.ControlMask
    Shift = x11.ShiftMask
    zoom_in = lambda: slots.zoom(+1)
    bindings: list[tuple[int, int, Callable[[], None]]] = [
        (x11.XK_p,        Ctrl | Shift, slots.open_preferences),
        (x11.XK_o,        Ctrl | Shift, slots.add_repo),
        (x11.XK_q,        Ctrl | Shift, slots.quit),
        (x11.XK_F1,       0,            slots.open_shortcuts),
        (x11.XK_Tab,      Ctrl,         lambda: slots.cycle_repo(+1)),
        (x11.XK_Tab,      Ctrl | Shift, lambda: slots.cycle_repo(-1)),
        # Ctrl+= / Ctrl++: both "zoom in" because the unshifted glyph
        # depends on layout (US: '=', some EU layouts: '+').
        (x11.XK_equal,    Ctrl,         zoom_in),
        (x11.XK_plus,     Ctrl,         zoom_in),
        (x11.XK_minus,    Ctrl,         lambda: slots.zoom(-1)),
        (x11.XK_0,        Ctrl,         lambda: slots.zoom(0)),
    ]
    # Ctrl+Shift+1..9 → jump to sidebar row 1..9 (zero-indexed internally).
    # ASCII digit keysyms are contiguous, so XK_1 + n - 1 is the keysym
    # for digit n. range(1, 10) deliberately excludes XK_0 — Ctrl+Shift+0
    # is reserved for a possible future "last row" / "10th row" binding;
    # mapping it now and changing later would break muscle memory.
    for n in range(1, 10):
        bindings.append((
            x11.XK_1 + (n - 1),
            Ctrl | Shift,
            lambda row=n - 1: slots.jump_to_row(row),
        ))
    return bindings
