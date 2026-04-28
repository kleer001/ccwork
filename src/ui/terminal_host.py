"""QWidget that embeds an `xterm` process via XEmbed (-into self.winId()).

xterm reparents itself into our X window on startup. On container resize we
grow/shrink xterm's X window to match, which xterm reacts to by updating the
PTY size and forwarding SIGWINCH to its child shell.

MVP limitations:
- Linux / X11 only. Under Wayland, force `QT_QPA_PLATFORM=xcb` at app startup
  so both Qt and xterm run through XWayland.
- `xterm` must be on PATH. We don't fall back silently — if absent, the host
  emits `failed(str)`.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import signal
from collections.abc import Sequence

from PySide6.QtCore import QProcess, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent, QMouseEvent, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import QWidget

from src.core import x11, xterm_osc
from src.core.settings import XtermSettings
from src.core.x11 import XDisplay

log = logging.getLogger(__name__)


# Milliseconds between child-window appearance polls after spawn. xterm takes
# one or two X round-trips to reparent into our window, so ~30 ms is plenty.
_POLL_INTERVAL_MS = 30
_POLL_TIMEOUT_MS = 3000


class TerminalHost(QWidget):
    """Embeds a single `xterm` process inside this widget.

    Emits:
        started: xterm process spawned (the X window may still be reparenting).
        embedded: xterm's X window is now a child of ours — ready to resize.
        finished(int): xterm process exited with the given code.
        failed(str):  spawn failed or xterm is missing.
    """

    started = Signal()
    embedded = Signal()
    finished = Signal(int)
    failed = Signal(str)
    # +1 = zoom in, -1 = zoom out, 0 = reset to saved pref.
    zoom_requested = Signal(int)
    # +1 = next repo, -1 = previous repo (Ctrl+Tab / Ctrl+Shift+Tab).
    cycle_repo_requested = Signal(int)
    # User right-clicked inside the terminal — pass the global position so
    # MainWindow can pop a context menu.
    context_menu_requested = Signal(object)  # QPoint

    def __init__(
        self,
        argv: Sequence[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._argv = list(argv)
        self._env = env
        self._cwd = cwd
        self._process: QProcess | None = None
        self._xterm_win: int | None = None
        self._xdisplay: XDisplay | None = None
        self._poll_elapsed = 0

        # Qt must create a real X window for this widget — xterm needs a
        # stable WId to reparent into. Without WA_NativeWindow, the widget
        # may share its parent's X window and our winId() is meaningless.
        self.setAttribute(Qt.WA_NativeWindow, True)
        # No Qt-side painting under the xterm — also avoids flicker.
        self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(200, 120)

    # ── lifecycle ──

    def start(self) -> None:
        """Spawn xterm. Idempotent if already running."""
        if self._process is not None:
            return
        if not shutil.which("xterm"):
            self.failed.emit("xterm not found on PATH — install it (e.g. `sudo apt install xterm`)")
            return

        # Ensure winId() exists by forcing the X window creation now.
        self.winId()

        argv = self._build_argv()
        proc = QProcess(self)
        if self._cwd:
            proc.setWorkingDirectory(self._cwd)
        if self._env is not None:
            # Merge with current environment so PATH/HOME/etc. remain usable.
            merged = os.environ.copy()
            merged.update(self._env)
            from PySide6.QtCore import QProcessEnvironment
            qenv = QProcessEnvironment()
            for k, v in merged.items():
                qenv.insert(k, v)
            proc.setProcessEnvironment(qenv)
        # Detach xterm's own stdio from Qt: we don't read it, and letting Qt
        # buffer it could mask errors.
        proc.setProcessChannelMode(QProcess.ForwardedChannels)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        proc.start(argv[0], argv[1:])
        self._process = proc

        self.started.emit()

        # Begin polling for the reparented child window.
        self._poll_elapsed = 0
        QTimer.singleShot(_POLL_INTERVAL_MS, self._poll_for_child)

    def focus_child(self) -> None:
        """Move X input focus to the embedded xterm, if attached yet."""
        if self._xterm_win and self._xdisplay is not None:
            self._xdisplay.set_input_focus(self._xterm_win)

    def stop(self) -> None:
        """Terminate xterm. The shell underneath dies with it."""
        if self._process is None:
            return
        # Disconnect BEFORE tearing down so a late queued finished/errorOccurred
        # can't re-enter our slots after _process is None.
        with contextlib.suppress(RuntimeError, TypeError):
            self._process.finished.disconnect(self._on_finished)
        with contextlib.suppress(RuntimeError, TypeError):
            self._process.errorOccurred.disconnect(self._on_error)
        if self._process.state() != QProcess.NotRunning:
            self._process.terminate()
            if not self._process.waitForFinished(2000):
                self._process.kill()
                self._process.waitForFinished(1000)
        self._process = None
        self._xterm_win = None
        if self._xdisplay is not None:
            self._xdisplay.close()
            self._xdisplay = None

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop()
        super().closeEvent(event)

    # ── embedding ──

    def _build_argv(self) -> list[str]:
        """Compose the full xterm argv, prepending -into <our winId>.

        The caller-supplied argv is expected to already contain any xterm
        flags the user chose (font, scrollback, extra_args) followed by the
        -e <cmd ...> tail. We only prepend the invariants (-into + WId).
        """
        wid = int(self.winId())
        return ["xterm", "-into", str(wid), *self._argv]

    def _poll_for_child(self) -> None:
        """Look for our X window's first child — that's xterm."""
        if self._process is None:
            return
        if self._xdisplay is None:
            try:
                self._xdisplay = XDisplay()
            except RuntimeError as e:
                self.failed.emit(f"X11 unavailable: {e}")
                return
        try:
            children = self._xdisplay.query_children(int(self.winId()))
        except OSError as e:  # pragma: no cover — libX11 error path
            self.failed.emit(f"XQueryTree failed: {e}")
            return

        if children:
            # First child: the xterm that reparented into us.
            self._xterm_win = children[0]
            self._fit_child_to_self()
            self._install_zoom_grabs()
            self.embedded.emit()
            return

        self._poll_elapsed += _POLL_INTERVAL_MS
        if self._poll_elapsed >= _POLL_TIMEOUT_MS:
            self.failed.emit("timed out waiting for xterm to embed (is $DISPLAY set?)")
            return
        QTimer.singleShot(_POLL_INTERVAL_MS, self._poll_for_child)

    def _fit_child_to_self(self) -> None:
        """Resize the embedded xterm X window to our current pixel size."""
        if self._xterm_win is None or self._xdisplay is None:
            return
        w = max(1, self.width())
        h = max(1, self.height())
        self._xdisplay.move_resize_window(self._xterm_win, 0, 0, w, h)
        self._xdisplay.flush()
        # A SIGWINCH nudge is harmless if xterm already saw ConfigureNotify,
        # and insures against xterm missing the event on very fast resizes.
        self._kick_sigwinch()

    def _kick_sigwinch(self) -> None:
        if self._process is None:
            return
        pid = int(self._process.processId())
        if pid <= 0:
            return
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGWINCH)

    # ── live settings ──

    def apply_live_settings(self, settings: XtermSettings) -> list[str]:
        """Apply what we can of `settings` to the running xterm without a
        restart. Returns fields that require a respawn to take effect.
        """
        if self._process is None:
            return ["<no running terminal>"]
        pid = int(self._process.processId())
        if pid <= 0:
            return ["<no pid>"]
        return xterm_osc.apply_live(pid, settings)

    def is_running(self) -> bool:
        """True iff the xterm QProcess is currently running."""
        if self._process is None:
            return False
        return bool(self._process.state() != QProcess.NotRunning)

    def paste_text(self, text: str) -> bool:
        """Write `text` directly to the child shell's PTY — used by the
        context menu's Paste action. Returns True on success."""
        if not text or self._process is None:
            return False
        pid = int(self._process.processId())
        if pid <= 0:
            return False
        pty = xterm_osc.find_child_pty(pid)
        if pty is None:
            return False
        return xterm_osc.write_to_pty(pty, text)

    # ── input shortcuts (Ctrl+zoom, Ctrl+Tab repo cycle, right-click menu) ──

    # Keysyms we grab under plain Ctrl. Ctrl+= is the canonical "zoom in"
    # because it doesn't require Shift on US layouts; Ctrl++ is also grabbed
    # so Shift+Ctrl+= keeps working for plus-key muscle memory.
    _ZOOM_KEYS = (
        (x11.XK_equal, +1),
        (x11.XK_plus,  +1),
        (x11.XK_minus, -1),
        (x11.XK_0,      0),  # reset
    )
    # Right mouse button we grab for the context menu. Button3 = plain
    # right-click; xterm's own native Ctrl+Button3 menu is left alone.
    _RMB = 3

    def _install_zoom_grabs(self) -> None:
        """Ask the X server to route our shortcut combos to us, not the
        embedded xterm. Safe if xdisplay isn't open — silently skips."""
        if self._xdisplay is None:
            return
        wid = int(self.winId())
        for keysym, _ in self._ZOOM_KEYS:
            self._xdisplay.grab_key(wid, keysym, x11.ControlMask)
        self._xdisplay.grab_button(wid, x11.Button4, x11.ControlMask)
        self._xdisplay.grab_button(wid, x11.Button5, x11.ControlMask)
        # Ctrl+Tab and Ctrl+Shift+Tab for repo cycling.
        self._xdisplay.grab_key(wid, x11.XK_Tab, x11.ControlMask)
        self._xdisplay.grab_key(wid, x11.XK_Tab, x11.ControlMask | x11.ShiftMask)
        # Plain right-click for the context menu.
        self._xdisplay.grab_button(wid, self._RMB, 0)
        self._xdisplay.flush()

    def _uninstall_zoom_grabs(self) -> None:
        if self._xdisplay is None:
            return
        wid = int(self.winId())
        for keysym, _ in self._ZOOM_KEYS:
            self._xdisplay.ungrab_key(wid, keysym, x11.ControlMask)
        self._xdisplay.ungrab_button(wid, x11.Button4, x11.ControlMask)
        self._xdisplay.ungrab_button(wid, x11.Button5, x11.ControlMask)
        self._xdisplay.ungrab_key(wid, x11.XK_Tab, x11.ControlMask)
        self._xdisplay.ungrab_key(wid, x11.XK_Tab, x11.ControlMask | x11.ShiftMask)
        self._xdisplay.ungrab_button(wid, self._RMB, 0)
        self._xdisplay.flush()

    # ── event handlers ──

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Only our grabbed combos reach Qt while xterm has focus; anything
        # else slips through to super().
        mods = event.modifiers()
        if mods & Qt.ControlModifier:
            key = event.key()
            if key in (Qt.Key_Equal, Qt.Key_Plus):
                self.zoom_requested.emit(+1)
                event.accept()
                return
            if key == Qt.Key_Minus:
                self.zoom_requested.emit(-1)
                event.accept()
                return
            if key == Qt.Key_0:
                self.zoom_requested.emit(0)
                event.accept()
                return
            if key in (Qt.Key_Tab, Qt.Key_Backtab):
                # Qt turns Ctrl+Shift+Tab into Key_Backtab (which drops the
                # Shift modifier). Either form means "cycle backward".
                delta = -1 if (key == Qt.Key_Backtab or mods & Qt.ShiftModifier) else +1
                self.cycle_repo_requested.emit(delta)
                event.accept()
                return
        super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.ControlModifier:
            dy = event.angleDelta().y()
            if dy > 0:
                self.zoom_requested.emit(+1)
            elif dy < 0:
                self.zoom_requested.emit(-1)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Our Ctrl-less right-click grab routes plain Button3 to us — use
        # it to surface a Qt context menu. The xterm native Ctrl+Button3
        # options menu is untouched (we only grab plain right-click).
        if event.button() == Qt.RightButton and not (event.modifiers() & Qt.ControlModifier):
            self.context_menu_requested.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_child_to_self()

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self.finished.emit(int(exit_code))

    def _on_error(self, error: QProcess.ProcessError) -> None:
        # Translate to a human message. The dominant failure is FailedToStart
        # (xterm missing). Other errors are rare but still worth surfacing.
        msg = {
            QProcess.FailedToStart: "xterm failed to start",
            QProcess.Crashed:       "xterm crashed",
            QProcess.Timedout:      "xterm timed out",
            QProcess.WriteError:    "xterm write error",
            QProcess.ReadError:     "xterm read error",
        }.get(error, f"xterm error ({error})")
        self.failed.emit(msg)
