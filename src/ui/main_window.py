"""MainWindow — the top-level Qt layout.

Structure:

    ┌──────────────────────────────────────────────────────────┐
    │           repo · branch              🔊   🔔   ⚙          │  ← thin top bar
    ├──────────┬───────────────────────────────────────────────┤
    │  Repo    │              Terminal stack                   │
    │ Sidebar  │   (one TerminalHost per repo, swapped         │
    │          │    by QStackedWidget on selection)            │
    └──────────┴───────────────────────────────────────────────┘

The 🔔 is a visual-only indicator — a red dot appears when Stop/Notification
events arrive; clicking clears the dot. There's no popover list (desktop
notify-send handles the text). The 🔊 / 🔇 toolbutton mirrors the
"Show desktop notifications" Preferences checkbox — one click mute,
shared state. Keyboard shortcuts (Ctrl+Shift+P/O/Q for prefs/add/quit,
Ctrl+Tab to cycle, Ctrl+Shift+1..9 for row jumps, Ctrl+= / Ctrl+- /
Ctrl+0 for zoom, F1 for the shortcut cheatsheet) are wired through a
passive XGrabKey on MainWindow's own X window rather than Qt's
QAction shortcut system — see ``_install_global_keys`` for why.
The grab is scoped to MainWindow's X subtree so it fires when ccwork
has focus (sidebar, terminal, dialog) but not when another app does.
"""

from __future__ import annotations

import base64
import binascii
import logging

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pathlib import Path

from src import __version__
from src.core.hook_server import (
    EVENT_NOTIFICATION,
    EVENT_REPO_ADDED,
    EVENT_STOP,
    EVENT_USER_PROMPT_SUBMIT,
    IDLE_EVENTS,
    HookServer,
)
from src.core.key_grab import (
    KeyGrabFilter,
    MainWindowSlots,
    build_main_window_bindings,
)
from src.core.repo_store import Repo, RepoStore
from src.core.settings import Settings, load_settings, save_settings
from src.core.terminal_session import build_session
from src.core import x11
from src.core.x11 import XDisplay
from src.ui.bell_button import BellButton
from src.ui.ctrl_c_warning import show_ctrl_c_warning
from src.ui.empty_state import EmptyState
from src.ui.preferences_dialog import PreferencesDialog
from src.ui.qt_theme import apply_theme
from src.ui.repo_sidebar import RepoSidebar
from src.ui.shortcuts_dialog import ShortcutsDialog
from src.ui.terminal_context_menu import build_terminal_menu
from src.ui.terminal_host import TerminalHost
from src.ui.title_label import TitleLabel


# Logo lives at <repo>/logo/v2-icon.svg. Resolve relative to this module
# the same way src/main.py does for the window icon, so an installed
# package and an in-tree run both find it without a runtime config lookup.
_LOGO_PATH = Path(__file__).resolve().parent.parent.parent / "logo" / "v2-icon.svg"


log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(
        self,
        store: RepoStore,
        hook_server: HookServer,
        settings: Settings | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ccwork")
        # First-run fallback. restoreGeometry runs at the end of __init__
        # and overrides this when a valid saved blob exists.
        self.resize(1280, 820)

        self._store = store
        self._hook_server = hook_server
        self._settings = settings if settings is not None else Settings()
        # One TerminalHost per repo *instance* (not per path) — duplicates of
        # the same repo each get their own xterm. Keyed by Repo.id so the two
        # rows for one path can't collide on a path-string key.
        self._terminals: dict[str, TerminalHost] = {}
        # Lazy — populated by _install_global_keys when running under xcb.
        self._key_xdisplay: XDisplay | None = None
        self._key_filter: KeyGrabFilter | None = None
        self._key_grab_window: int = 0
        self._key_bindings: list[tuple[int, int]] = []
        # Tracked separately from `_key_bindings` so it can be installed /
        # removed at runtime as the user toggles ``ui.warn_on_ctrl_c``.
        self._ctrl_c_grabbed: bool = False
        # Re-entrancy guard: while the modal warning is up, a second
        # Ctrl+C must not stack another dialog.
        self._ctrl_c_dialog_open: bool = False

        # ── top strip: centered repo · branch + right-side icon cluster ──
        self._title = TitleLabel(self)

        self._alerts_btn = QToolButton(self)
        self._alerts_btn.setAutoRaise(True)
        self._alerts_btn.setCheckable(True)
        self._alerts_btn.setChecked(self._settings.ui.desktop_notifications)
        self._refresh_alerts_button()
        self._alerts_btn.toggled.connect(self._on_alerts_toggled)

        self._bell_btn = BellButton(self)
        self._bell_btn.setToolTip("Unread alerts — click to clear")
        self._bell_btn.clicked.connect(lambda: self._bell_btn.set_unseen(False))

        self._gear_btn = QToolButton(self)
        self._gear_btn.setText("⚙")        # ⚙
        self._gear_btn.setToolTip("Preferences (Ctrl+Shift+P)")
        self._gear_btn.setAutoRaise(True)
        self._gear_btn.clicked.connect(self._open_preferences)

        top = QWidget(self)
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(6, 2, 6, 2)
        top_lay.setSpacing(4)
        top_lay.addWidget(self._title, 1)        # absorbs all slack so label sits centered
        top_lay.addWidget(self._alerts_btn, 0)
        top_lay.addWidget(self._bell_btn, 0)
        top_lay.addWidget(self._gear_btn, 0)
        top.setFixedHeight(32)

        # ── body: sidebar + terminal stack ──
        self._sidebar = RepoSidebar(self._store, self, settings=self._settings)
        self._stack = QStackedWidget(self)
        self._empty_placeholder = self._make_empty_placeholder()
        self._stack.addWidget(self._empty_placeholder)
        self._stack.setCurrentWidget(self._empty_placeholder)

        splitter = QSplitter(Qt.Horizontal, self)
        self._splitter = splitter
        # Debounce sidebar-width persistence: drags fire splitterMoved many
        # times per second, but we only need to write the final value.
        self._sidebar_save_timer = QTimer(self)
        self._sidebar_save_timer.setInterval(
            self._settings.ui.animation.splitter_debounce_ms
        )
        self._sidebar_save_timer.setSingleShot(True)
        self._sidebar_save_timer.timeout.connect(self._persist_settings_now)
        self._apply_sidebar_layout()
        self._sidebar.set_badge_style(self._settings.ui.status_badge_style)
        splitter.splitterMoved.connect(self._on_splitter_moved)

        # ── assemble ──
        central = QWidget(self)
        v = QVBoxLayout(central)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        v.addWidget(top)
        v.addWidget(splitter, 1)
        self.setCentralWidget(central)

        # ── shortcuts: XGrabKey on MainWindow + QAbstractNativeEventFilter ──
        # Same mechanism as Skycoder42/QHotkey and CopyQ's QxtGlobalShortcut
        # (passive grab + native event filter), but scoped to MainWindow's
        # own X window instead of root — fires for any focus inside our
        # subtree (Qt widgets + XEmbed'd xterm), stays out of the way when
        # another app is focused.
        self._install_global_keys()

        # ── wiring ──
        self._sidebar.repo_selected.connect(self._on_repo_selected)
        self._sidebar.repo_added.connect(self._on_repo_added)
        self._sidebar.reload_requested.connect(self._reload_terminal)
        self._sidebar.repo_removed.connect(self._on_repo_removed)
        self._sidebar.path_copied.connect(self._on_path_copied)
        self._sidebar.model.working_changed.connect(self._refresh_title)
        self._hook_server.event_received.connect(self._on_hook_event)

        # Light the "last focused" violet dot on the repo the user was on
        # when they last closed ccwork. Visible until they click that row
        # (which clears it as part of normal selection-change behavior).
        if self._settings.last_focused_repo:
            self._sidebar.set_last_focused(self._settings.last_focused_repo)

        # Optionally re-open that repo's terminal so the user lands where
        # they left off. Defer one tick so the window is shown first
        # (xterm reparents into a mapped X window).
        if (
            self._settings.ui.restore_last_repo
            and self._settings.last_focused_repo
            and self._sidebar.model.index_of(self._settings.last_focused_repo) >= 0
        ):
            QTimer.singleShot(0, lambda: self._sidebar.select_path(self._settings.last_focused_repo))

        # Restore saved window geometry last — after the child hierarchy is
        # in place (Qt documents that restoreGeometry should run post-
        # setCentralWidget). The earlier self.resize(1280, 820) is the
        # fallback for first-run / corrupt-blob / Qt-version-skew cases.
        self._restore_window_geometry()

        # Make the empty-suffix invariant explicit on first paint — the
        # initial setWindowTitle("ccwork") above is correct at count=0, but
        # calling _refresh_title here documents that the title is always
        # signal-driven and there's no manual setWindowTitle path that the
        # counter logic could miss.
        self._refresh_title()

    # ── shortcuts ──

    def _install_global_keys(self) -> None:
        """Install one passive XGrabKey per shortcut on MainWindow's own
        X window, paired with a single ``QAbstractNativeEventFilter`` on
        the ``QApplication``. Skipped under any non-xcb Qt platform
        (offscreen tests, Wayland-without-XWayland), where there is no X
        display to grab on.

        Grabbing on ``self.winId()`` rather than ``DefaultRootWindow``
        gives **app-scoped** shortcuts: the X11 passive-grab activation
        condition is "grab_window is an ancestor of (or is) the focus
        window," and MainWindow is an ancestor of every Qt widget and
        of the XEmbed'd xterm (which lives inside a TerminalHost child
        widget). So:

          • Sidebar focused → MainWindow in focus chain → grab fires. ✓
          • xterm focused (XEmbed'd) → MainWindow in focus chain → grab
            fires. ✓
          • Firefox / any other app focused → MainWindow NOT in focus
            chain → grab silently doesn't activate, the other app sees
            the press normally. ✓

        The QAction/ApplicationShortcut path won't fire when xterm holds
        X input focus because xterm isn't a Qt widget — that's the whole
        reason we bypass Qt's shortcut system here. Root grabs would be
        global; MainWindow-scoped grabs aren't.
        """
        app = QApplication.instance()
        plat = app.platformName() if app is not None else None
        if plat != "xcb":
            log.info("global keys: skipped (platform=%r)", plat)
            return
        # We must grab on Qt's *own* X connection — XGrabKey delivers events
        # to the grabber's connection, so a grab installed on a separately
        # XOpenDisplay'd handle is invisible to Qt's QAbstractNativeEventFilter.
        # PySide6 ≥ 6.6 (our pinned minimum) exposes the underlying Display*
        # via QX11Application; on xcb that's guaranteed non-null, so we let
        # any breakage here crash loudly rather than silently disable keys.
        iface = app.nativeInterface()
        self._key_xdisplay = XDisplay.attach(int(iface.display()))
        self._key_filter = KeyGrabFilter(self._key_xdisplay)
        app.installNativeEventFilter(self._key_filter)
        # Force creation of MainWindow's X window now (winId() is lazy on
        # QMainWindow) so XGrabKey has a real Window to install on. The
        # grab persists for the app's lifetime — no per-TerminalHost
        # lifecycle to track, and it's not global so other apps' keys are
        # untouched.
        self._key_grab_window = int(self.winId())

        bindings = build_main_window_bindings(MainWindowSlots(
            open_preferences=self._open_preferences,
            add_repo=self._sidebar.add_repo_via_dialog,
            quit=self.close,
            open_shortcuts=self._open_shortcuts,
            cycle_repo=self._on_cycle_repo_requested,
            zoom=self._on_zoom_requested,
            jump_to_row=self._jump_to_row,
        ))

        # Track (keysym, mods) for ungrab on shutdown.
        self._key_bindings = [(ks, m) for ks, m, _ in bindings]
        for keysym, mods, callback in bindings:
            self._key_xdisplay.grab_key(self._key_grab_window, keysym, mods)
            self._key_filter.register(keysym, mods, callback)
        self._key_xdisplay.flush()
        log.info("global keys: %d shortcuts on MainWindow=0x%x",
                 len(bindings), self._key_grab_window)

        # Conditional Ctrl+C interception — installed only while the user
        # wants the warning, so when it's off Ctrl+C reaches xterm with
        # zero indirection. Toggled live from `_on_settings_changed`.
        if self._settings.ui.warn_on_ctrl_c:
            self._install_ctrl_c_grab()

    def _install_ctrl_c_grab(self) -> None:
        """Install the passive grab + filter entry for plain Ctrl+C. No-op
        if already installed or if the X grab infrastructure isn't up."""
        if self._ctrl_c_grabbed or self._key_xdisplay is None or self._key_filter is None:
            return
        self._key_xdisplay.grab_key(self._key_grab_window, x11.XK_c, x11.ControlMask)
        self._key_filter.register(x11.XK_c, x11.ControlMask, self._on_ctrl_c_pressed)
        self._key_xdisplay.flush()
        self._ctrl_c_grabbed = True
        log.info("Ctrl+C warning grab installed")

    def _uninstall_ctrl_c_grab(self) -> None:
        """Release the Ctrl+C grab so the keystroke flows straight to xterm."""
        if not self._ctrl_c_grabbed or self._key_xdisplay is None or self._key_filter is None:
            return
        try:
            self._key_xdisplay.ungrab_key(self._key_grab_window, x11.XK_c, x11.ControlMask)
            self._key_xdisplay.flush()
        except Exception:
            log.exception("Ctrl+C ungrab failed")
        self._key_filter.unregister(x11.XK_c, x11.ControlMask)
        self._ctrl_c_grabbed = False
        log.info("Ctrl+C warning grab removed")

    def _on_ctrl_c_pressed(self) -> None:
        """Show the warning dialog, then inject 0x03 if confirmed. Silently
        no-ops when no terminal is visible (Ctrl+C in the empty placeholder
        has nothing to interrupt) or when a previous dialog is still open."""
        if self._ctrl_c_dialog_open:
            return
        host = self._current_terminal_host()
        if host is None or not host.is_running():
            return
        self._ctrl_c_dialog_open = True
        try:
            result = show_ctrl_c_warning(self)
        finally:
            self._ctrl_c_dialog_open = False
        if result.send_signal:
            host.send_interrupt()
        if not result.keep_warning:
            self._settings.ui.warn_on_ctrl_c = False
            self._uninstall_ctrl_c_grab()
            self._save_settings_safely("Ctrl+C warning disabled")

    def _current_terminal_host(self) -> TerminalHost | None:
        """Return the TerminalHost currently shown in the stack, if any."""
        widget = self._stack.currentWidget()
        return widget if isinstance(widget, TerminalHost) else None

    def _uninstall_global_keys(self) -> None:
        """Release the root grabs and detach the native event filter. Safe
        to call multiple times and on a never-installed instance."""
        if self._key_xdisplay is None:
            return
        self._uninstall_ctrl_c_grab()
        try:
            for keysym, mods in self._key_bindings:
                self._key_xdisplay.ungrab_key(self._key_grab_window, keysym, mods)
            self._key_xdisplay.flush()
        except Exception:
            log.exception("global keys: ungrab failed")
        if self._key_filter is not None:
            app = QApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self._key_filter)
            self._key_filter = None
        self._key_xdisplay.close()
        self._key_xdisplay = None
        self._key_bindings = []

    def _jump_to_row(self, row: int) -> None:
        """Select sidebar row by zero-based index.

        Out-of-range presses (fewer than `row+1` repos) flash a transient
        status-bar hint so the keystroke registers visibly rather than
        feeling broken. `row+1` in the message because the user pressed
        a 1-indexed digit (`Ctrl+Shift+9` → "slot 9").
        """
        model = self._sidebar.model
        if row < 0 or row >= model.rowCount():
            self.statusBar().showMessage(f"No repo at slot {row + 1}", 1500)
            return
        repo = model.repo_at(row)
        if repo is not None:
            self._sidebar.select_id(repo.id)

    # ── sidebar layout (side + width) ──

    def _apply_sidebar_layout(self) -> None:
        """(Re)wire the splitter to honor ui.sidebar_side and sidebar_width.

        QSplitter lays children left→right in insertion order; "right side"
        means the stack goes first, sidebar second. We use insertWidget so
        an already-parented widget is *moved* rather than re-parented —
        critical for the TerminalHost's embedded xterm, which would lose
        its XEmbed if we briefly setParent(None) it.
        """
        sp = self._splitter
        side = self._settings.ui.sidebar_side
        width = max(60, min(600, int(self._settings.ui.sidebar_width)))
        if side == "right":
            sp.insertWidget(0, self._stack)
            sp.insertWidget(1, self._sidebar)
            sp.setStretchFactor(0, 1)
            sp.setStretchFactor(1, 0)
            total = max(sp.width(), width + 600)
            sp.setSizes([total - width, width])
        else:
            sp.insertWidget(0, self._sidebar)
            sp.insertWidget(1, self._stack)
            sp.setStretchFactor(0, 0)
            sp.setStretchFactor(1, 1)
            total = max(sp.width(), width + 600)
            sp.setSizes([width, total - width])

    def _on_splitter_moved(self, *_: object) -> None:
        """Note the dragged sidebar width and queue a debounced persist.

        splitterMoved fires once per drag pixel; without coalescing we'd
        rewrite settings.json dozens of times per drag.
        """
        sizes = self._splitter.sizes()
        if len(sizes) != 2:
            return
        side = self._settings.ui.sidebar_side
        new_width = sizes[1] if side == "right" else sizes[0]
        if new_width <= 0 or new_width == self._settings.ui.sidebar_width:
            return
        self._settings.ui.sidebar_width = int(new_width)
        self._sidebar_save_timer.start()  # restart resets the debounce window

    def _save_settings_safely(self, context: str = "settings") -> None:
        """Write settings to disk; log + swallow OSError. The three persist
        sites (sidebar-width drag, window geometry on close, last-focused
        repo on click) all want fail-soft behavior — a write error must
        not block the user action that triggered the save."""
        try:
            save_settings(self._settings)
        except OSError as e:
            log.warning("could not persist %s: %s", context, e)

    def _persist_settings_now(self) -> None:
        self._save_settings_safely("settings")

    def _restore_window_geometry(self) -> None:
        """Decode the persisted geometry blob and hand it to Qt. On any
        failure (no blob, base64 decode error, Qt version-skew rejection)
        log at WARNING and fall through to the 1280x820 set earlier in
        ``__init__``."""
        blob = self._settings.window.geometry
        if not blob:
            return
        try:
            data = base64.b64decode(blob.encode("ascii"))
        except (binascii.Error, ValueError) as e:
            log.warning("corrupt window.geometry blob (%s) — using default", e)
            return
        if not self.restoreGeometry(data):
            log.warning("restoreGeometry rejected the saved blob "
                        "(Qt version skew?) — using default")

    def _persist_window_state(self) -> None:
        """Stamp the current geometry into Settings and write to disk.
        A save failure here must not block quit — `_save_settings_safely`
        swallows the OSError."""
        blob = bytes(self.saveGeometry())
        self._settings.window.geometry = base64.b64encode(blob).decode("ascii")
        self._save_settings_safely("window geometry")

    def _refresh_alerts_button(self) -> None:
        on = bool(self._settings.ui.desktop_notifications)
        self._alerts_btn.setText("🔊" if on else "🔇")
        self._alerts_btn.setToolTip(
            "Desktop alerts on — click to mute" if on
            else "Desktop alerts muted — click to unmute"
        )

    def _on_alerts_toggled(self, on: bool) -> None:
        if self._settings.ui.desktop_notifications == on:
            return
        self._settings.ui.desktop_notifications = on
        self._refresh_alerts_button()
        self._persist_settings_now()

    def _open_preferences(self) -> None:
        dlg = PreferencesDialog(self._settings, self)
        dlg.applied.connect(self._on_settings_changed)
        dlg.exec()

    def _open_shortcuts(self) -> None:
        """Show the modal cheatsheet. Triggered by F1 via the MainWindow-scoped
        grab table; also reachable from any future Help button wired to this slot."""
        ShortcutsDialog(self).exec()

    def _on_settings_changed(self, settings: Settings) -> None:
        # Keep the reference in sync so new terminal spawns pick it up.
        self._settings = settings

        # Re-apply sidebar side / width — cheap, and the only way the user
        # sees their UI-tab edits without restarting.
        self._apply_sidebar_layout()
        self._sidebar.set_badge_style(settings.ui.status_badge_style)
        # Hand the sidebar the fresh Settings object so it picks up
        # auto_arrange_repos toggles without a restart.
        self._sidebar.set_settings(settings)
        # Toolbar mute glyph mirrors the Preferences checkbox.
        with QSignalBlocker(self._alerts_btn):
            self._alerts_btn.setChecked(settings.ui.desktop_notifications)
        self._refresh_alerts_button()

        # Sync the Ctrl+C interception with the (possibly toggled) pref.
        if settings.ui.warn_on_ctrl_c:
            self._install_ctrl_c_grab()
        else:
            self._uninstall_ctrl_c_grab()

        # Repaint the Qt chrome with the same palette as the terminal.
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, settings)

        # Live-apply what we can (colors + font face + size) to every running
        # terminal. Startup-only settings (scrollback, scrollbar, …) still
        # need respawn.
        needs_restart_fields: set[str] = set()
        live_applied = 0
        for host in self._terminals.values():
            unapplied = host.apply_live_settings(settings.xterm)
            if unapplied:
                needs_restart_fields.update(unapplied)
            live_applied += 1

        if live_applied == 0:
            return  # no running terminals; nothing to say

        # Only fields the user actually changed from defaults might matter.
        # For the message we care about "has the user set a value that xterm
        # can only read at startup?" — which in practice just means any
        # open terminal might want a reload to fully match. Keep the hint
        # brief; users who care will right-click → Reload.
        bar = self.statusBar()
        if needs_restart_fields & {"font_size", "scrollback", "scrollbar", "jump_scroll", "extra_args"}:
            bar.showMessage(
                "Colors applied live. Right-click a repo → Reload terminal to "
                "pick up font-size / scrollback / scrollbar changes.",
                10_000,
            )
        else:
            bar.showMessage("Settings applied.", 3_000)

    def _on_repo_removed(self, repo: Repo) -> None:
        """A repo was removed from the sidebar — also tear down its terminal."""
        host = self._terminals.pop(repo.id, None)
        if host is not None:
            was_current = self._stack.currentWidget() is host
            self._stack.removeWidget(host)
            host.stop()
            host.deleteLater()
            if was_current:
                self._stack.setCurrentWidget(self._empty_placeholder)
                self._title.set_repo(None, None)

    def _reload_terminal(self, repo: Repo) -> None:
        """Respawn the terminal for a repo with the current settings.

        Killing xterm kills the shell inside; any live Claude session is
        lost. Callers should confirm with the user before invoking.
        """
        host = self._terminals.pop(repo.id, None)
        if host is not None:
            self._stack.removeWidget(host)
            host.stop()
            host.deleteLater()
        # Re-spawn.
        self._ensure_terminal(repo)

    # ── zoom ──

    # Matches the Preferences dialog range so a zoomed value round-trips
    # cleanly through Save without the spinbox clamping it silently.
    _FONT_SIZE_MIN = 6
    _FONT_SIZE_MAX = 48

    def _on_zoom_requested(self, delta: int) -> None:
        """Handle Ctrl+=/Ctrl+-/Ctrl+0/Ctrl+scroll from any TerminalHost.

        +1/-1 nudge the current font size by one point and live-apply to
        every running terminal. 0 reloads the on-disk setting so the user
        can bail out of a zoom session. Transient zooms are NOT persisted —
        quit+reopen restores the saved pref, matching konsole's default.
        """
        if delta == 0:
            # Reset: re-read from disk. If the file is gone or unreadable,
            # load_settings falls back to defaults, which is fine.
            self._settings = load_settings()
        else:
            cur = int(self._settings.xterm.font_size)
            new = max(self._FONT_SIZE_MIN, min(self._FONT_SIZE_MAX, cur + delta))
            if new == cur:
                return  # at the clamp — nothing to do
            self._settings.xterm.font_size = new

        for host in self._terminals.values():
            host.apply_live_settings(self._settings.xterm)

        self.statusBar().showMessage(f"Font size: {self._settings.xterm.font_size}pt", 1500)

    # ── repo cycling (Ctrl+Tab / Ctrl+Shift+Tab) ──

    def _on_cycle_repo_requested(self, delta: int) -> None:
        """Move the sidebar selection by `delta` (wrapping). Empty sidebar
        or delta=0 is a no-op."""
        model = self._sidebar.model
        n = model.rowCount()
        if n <= 1 or delta == 0:
            return
        cur_id = self._current_repo_id()
        cur_row = model.index_of_id(cur_id) if cur_id else -1
        next_row = (cur_row + delta) % n
        repo = model.repo_at(next_row)
        if repo is not None:
            self._select_repo(repo)

    # ── terminal context menu ──

    def _on_terminal_context_menu(self, repo: Repo, global_pos) -> None:
        """Build and exec the right-click-in-terminal menu. The labels,
        tooltip, and disabled Copy hint live in ``terminal_context_menu``;
        this method just supplies the callbacks bound to the current repo."""
        menu = build_terminal_menu(
            parent=self,
            on_paste=lambda: self._paste_clipboard_to(repo),
            on_reload=lambda: self._sidebar._confirm_reload(repo),
            on_preferences=self._open_preferences,
        )
        menu.exec(global_pos)

    def _paste_clipboard_to(self, repo: Repo) -> None:
        from PySide6.QtWidgets import QApplication
        host = self._terminals.get(repo.id)
        if host is None:
            return
        host.paste_text(QApplication.clipboard().text())

    # ── helpers ──

    def _make_empty_placeholder(self) -> QWidget:
        """Construct the placeholder shown when no terminal is current.

        Same widget instance is reused for both empty-states (cold start
        with no repos, and a terminal that just exited while it was
        visible). See `src/ui/empty_state.py` for the layout.
        """
        return EmptyState(version=__version__, logo_path=_LOGO_PATH, parent=self)

    def _ensure_terminal(self, repo: Repo) -> TerminalHost:
        """Lazy-spawn a TerminalHost for the given repo."""
        host = self._terminals.get(repo.id)
        if host is not None:
            return host
        spec = build_session(repo, xterm_settings=self._settings.xterm)
        host = TerminalHost(
            argv=spec.argv,
            env=spec.env,
            cwd=spec.cwd,
            parent=self._stack,
        )
        host.failed.connect(lambda msg, r=repo: self._on_terminal_failed(r, msg))
        host.finished.connect(lambda code, r=repo: self._on_terminal_finished(r, code))
        host.zoom_requested.connect(self._on_zoom_requested)
        host.context_menu_requested.connect(
            lambda pos, r=repo: self._on_terminal_context_menu(r, pos)
        )
        self._terminals[repo.id] = host
        self._sidebar.set_terminal_active(repo.id, True)
        self._stack.addWidget(host)
        # Make the host current + visible BEFORE starting xterm so the parent
        # X window is mapped when xterm reparents into it.
        self._stack.setCurrentWidget(host)
        host.start()
        return host

    # ── slots ──

    def _on_repo_selected(self, repo: Repo) -> None:
        # Refresh branches first so the title gets a fresh subtitle on click.
        self._sidebar.refresh_branches()
        self._title.set_repo(repo.display_name, self._branch_for(repo.path))
        # _ensure_terminal handles setCurrentWidget on first spawn; for a
        # pre-existing host we still need to swap to it.
        host = self._ensure_terminal(repo)
        self._stack.setCurrentWidget(host)
        host.focus_child()
        # Persist so the violet dot can be restored next launch. Best-effort:
        # a write failure here shouldn't block the click. last_focused_repo
        # is path-keyed (matches whichever instance happens to be at that
        # path on next launch — duplicates don't survive across restarts in
        # any meaningful "which one was active" sense).
        if self._settings.last_focused_repo != repo.path:
            self._settings.last_focused_repo = repo.path
            self._save_settings_safely("last_focused_repo")

    def _select_repo(self, repo: Repo) -> None:
        """Convenience for keyboard-cycle: pick a specific repo by id."""
        self._sidebar.select_id(repo.id)

    def changeEvent(self, event) -> None:
        # When the window gains activation (alt-tab, taskbar click), forward
        # X input focus to the currently selected repo's xterm. Deferred to
        # the next tick so Qt's own activation bookkeeping has settled.
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            current = self._stack.currentWidget()
            if isinstance(current, TerminalHost):
                QTimer.singleShot(0, current.focus_child)

    def _branch_for(self, path: str) -> str | None:
        """Pull the cached branch for `path` from the sidebar model."""
        from src.ui.repo_sidebar import ROLE_BRANCH
        row = self._sidebar.model.index_of(path)
        if row < 0:
            return None
        return self._sidebar.model.data(self._sidebar.model.index(row), ROLE_BRANCH)

    def _on_repo_added(self, repo: Repo) -> None:
        self._sidebar.refresh_branches()

    def _on_path_copied(self, path: str) -> None:
        """Flash a status-bar confirmation after `RepoSidebar._copy_path`.

        Middle-elides the path so a very long absolute path doesn't push the
        status bar wider than the window or smear off-screen. `- 80 px`
        reserves room for the `"Copied: "` prefix plus padding.
        """
        bar = self.statusBar()
        fm = QFontMetrics(bar.font())
        width = max(100, bar.width() - 80)
        elided = fm.elidedText(path, Qt.ElideMiddle, width)
        bar.showMessage(f"Copied: {elided}", 2000)

    def _refresh_title(self) -> None:
        """Recompute the window title from the model's working-count.

        Count is path-keyed (matches `_working`'s normalized-path
        membership), so duplicate rows on the same path count once —
        "1 working" rather than "2 working" for one Claude session.
        Format: `ccwork` / `ccwork — 1 working` / `ccwork — N working`.
        Em dash so a future suffix (e.g. `, 1 needs attention`) composes.
        """
        n = len(self._sidebar.model.working_paths())
        if n == 0:
            self.setWindowTitle("ccwork")
        else:
            self.setWindowTitle(f"ccwork — {n} working")

    def _on_terminal_failed(self, repo: Repo, msg: str) -> None:
        log.warning("terminal for %s failed: %s", repo.path, msg)
        QMessageBox.warning(self, f"xterm failed for {repo.display_name}", msg)

    def _on_terminal_finished(self, repo: Repo, code: int) -> None:
        host = self._terminals.pop(repo.id, None)
        self._sidebar.set_terminal_active(repo.id, False)
        was_current = host is not None and self._stack.currentWidget() is host
        if host is not None:
            self._stack.removeWidget(host)
            host.deleteLater()
        # Working state is path-broadcast. If another terminal at this path
        # is still alive, leave the spinner — that other session may still
        # be mid-turn. Otherwise clear it.
        any_alive = any(
            r.id in self._terminals and self._terminals[r.id].is_running()
            for r in self._store.repos_for_path(repo.path)
            if r.id != repo.id
        )
        if not any_alive:
            self._sidebar.set_working(repo.path, False)
        # If the departing terminal was visible, show the placeholder so we
        # don't silently switch to some other repo's terminal.
        if was_current:
            self._stack.setCurrentWidget(self._empty_placeholder)
        log.info("terminal for %s exited (code=%d)", repo.path, code)

    def _on_hook_event(self, obj: dict) -> None:
        """Thin dispatcher: route by event type and delegate per-row state
        transitions to the sidebar's apply_hook_event entry point.

        Per-row state ownership lives entirely in RepoListModel — see the
        docstring on RepoListModel.apply_hook_event for the event →
        mutation table. This method only handles cross-cutting concerns:
        the RepoAdded auto-add and the bell-dot for idle events. The
        quit-confirm prompt derives its working list on demand from the
        model (closeEvent), so there's no id-keyed shadow state to
        maintain here.
        """
        event = str(obj.get("event", ""))
        payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
        cwd = obj.get("cwd") or (payload.get("cwd") if isinstance(payload, dict) else None)

        if event == EVENT_REPO_ADDED and cwd:
            # Auto-add only when no row exists yet for this path. Manual
            # Ctrl+O is the only way to create duplicates — every plain
            # `claude` invocation in an existing repo dir would otherwise
            # spawn a new tab.
            if not self._store.repos_for_path(str(cwd)):
                self._sidebar.model.add_repo(cwd)
            return

        # Resolve the cwd to every repo instance sharing that path. With
        # duplicates allowed, hooks can't tell duplicates apart by cwd alone
        # — sidebar state is path-keyed so a single apply_hook_event call
        # paints every matching row. Per-session routing is future work.
        matching: list[Repo] = (
            self._store.repos_for_path(str(cwd)) if cwd else []
        )
        log.info("hook event=%s cwd=%r matched=%d", event, cwd, len(matching))
        if not matching:
            return

        self._sidebar.apply_hook_event(event, str(cwd))

        if event in IDLE_EVENTS:
            # Bell dot: glanceable "something happened" signal even when
            # desktop notifications are off or the sidebar is scrolled.
            self._bell_btn.set_unseen(True)

    def _current_repo_id(self) -> str | None:
        w = self._stack.currentWidget()
        for repo_id, host in self._terminals.items():
            if host is w:
                return repo_id
        return None

    # ── lifecycle ──

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # Only nag when Claude is mid-turn somewhere — an idle shell sitting
        # at a prompt is fine to kill silently. Working state lives on the
        # model (path-keyed); we intersect with the set of repos that have
        # a running terminal here. Notification fires mid-turn and does
        # not clear working, so a permission_prompt still nags.
        model = self._sidebar.model
        working_ids = [
            rid for rid, host in self._terminals.items()
            if host.is_running() and model.is_working(self._store.find_by_id(rid).path)
        ]
        if working_ids:
            id_to_repo = {r.id: r for r in self._store.repos}
            names = ", ".join(
                id_to_repo[rid].display_name for rid in working_ids
                if rid in id_to_repo
            )
            ans = QMessageBox.question(
                self,
                "Quit ccwork?",
                f"Claude is working in {len(working_ids)} repo(s): {names}.\n\n"
                "Quitting kills those sessions mid-response. The conversation "
                "transcripts are preserved — run `claude --continue` to resume "
                "them — but any in-flight response is lost.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                event.ignore()
                return
        # Capture geometry before tearing down terminals — must happen on
        # the path past the working-session prompt so a cancelled quit
        # doesn't persist a transient size.
        self._persist_window_state()
        for host in list(self._terminals.values()):
            host.stop()
        self._terminals.clear()
        self._uninstall_global_keys()
        super().closeEvent(event)
