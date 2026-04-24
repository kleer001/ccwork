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

import logging
import os
import shutil
import signal
from typing import Sequence

from PySide6.QtCore import QProcess, QTimer, Signal, Qt
from PySide6.QtWidgets import QWidget

from src.core.settings import XtermSettings
from src.core.x11 import XDisplay
from src.core import xterm_osc


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

    def stop(self) -> None:
        """Terminate xterm. The shell underneath dies with it."""
        if self._process is None:
            return
        # Disconnect BEFORE tearing down so a late queued finished/errorOccurred
        # can't re-enter our slots after _process is None.
        try:
            self._process.finished.disconnect(self._on_finished)
        except (RuntimeError, TypeError):
            pass
        try:
            self._process.errorOccurred.disconnect(self._on_error)
        except (RuntimeError, TypeError):
            pass
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

    def closeEvent(self, event) -> None:  # type: ignore[override]
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
        try:
            os.kill(pid, signal.SIGWINCH)
        except ProcessLookupError:
            pass

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

    # ── event handlers ──

    def resizeEvent(self, event) -> None:  # type: ignore[override]
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
