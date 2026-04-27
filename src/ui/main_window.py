"""MainWindow — the top-level Qt layout.

Structure:

    ┌──────────────────────────────────────────────────────────┐
    │           repo · branch                   🔔   ⚙          │  ← thin top bar
    ├──────────┬───────────────────────────────────────────────┤
    │  Repo    │              Terminal stack                   │
    │ Sidebar  │   (one TerminalHost per repo, swapped         │
    │          │    by QStackedWidget on selection)            │
    └──────────┴───────────────────────────────────────────────┘

The 🔔 is a visual-only indicator — a red dot appears when Stop/Notification
events arrive; clicking clears the dot. There's no popover list (desktop
notify-send handles the text). Preferences/Add-Repo/Quit reachable via
Ctrl+,/Ctrl+O/Ctrl+Q — registered as window-level QActions so the menu bar
can stay gone.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter
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

from src.core.hook_server import HookServer
from src.core.repo_store import Repo, RepoStore
from src.core.settings import Settings, load_settings, save_settings
from src.core.terminal_session import build_session
from src.ui.preferences_dialog import PreferencesDialog
from src.ui.qt_theme import apply_theme
from src.ui.repo_sidebar import RepoSidebar, _norm as _norm_path
from src.ui.terminal_host import TerminalHost
from src.ui.title_label import TitleLabel


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
        self.resize(1280, 820)

        self._store = store
        self._hook_server = hook_server
        self._settings = settings if settings is not None else Settings()
        # One TerminalHost per repo path; created lazily on first selection.
        self._terminals: dict[str, TerminalHost] = {}
        # Repos whose Claude session is mid-turn (UserPromptSubmit fired,
        # Stop/Notification hasn't yet). Drives the quit-confirm prompt so we
        # only nag when there's actual in-flight work to lose.
        self._working: set[str] = set()

        # ── top strip: centered repo · branch + right-side icon cluster ──
        self._title = TitleLabel(self)

        self._bell_btn = _BellButton(self)
        self._bell_btn.setToolTip("Unread alerts — click to clear")
        self._bell_btn.clicked.connect(lambda: self._bell_btn.set_unseen(False))

        self._gear_btn = QToolButton(self)
        self._gear_btn.setText("⚙")        # ⚙
        self._gear_btn.setToolTip("Preferences (Ctrl+,)")
        self._gear_btn.setAutoRaise(True)
        self._gear_btn.clicked.connect(self._open_preferences)

        top = QWidget(self)
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(6, 2, 6, 2)
        top_lay.setSpacing(4)
        top_lay.addWidget(self._title, 1)        # absorbs all slack so label sits centered
        top_lay.addWidget(self._bell_btn, 0)
        top_lay.addWidget(self._gear_btn, 0)
        top.setFixedHeight(32)

        # ── body: sidebar + terminal stack ──
        self._sidebar = RepoSidebar(self._store, self)
        self._stack = QStackedWidget(self)
        self._empty_placeholder = self._make_empty_placeholder()
        self._stack.addWidget(self._empty_placeholder)
        self._stack.setCurrentWidget(self._empty_placeholder)

        splitter = QSplitter(Qt.Horizontal, self)
        self._splitter = splitter
        # Debounce sidebar-width persistence: drags fire splitterMoved many
        # times per second, but we only need to write the final value.
        self._sidebar_save_timer = QTimer(self)
        self._sidebar_save_timer.setInterval(300)
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

        # ── shortcuts (no menu bar — actions are window-level) ──
        self._install_shortcuts()

        # ── wiring ──
        self._sidebar.repo_selected.connect(self._on_repo_selected)
        self._sidebar.repo_added.connect(self._on_repo_added)
        self._sidebar.reload_requested.connect(self._reload_terminal)
        self._sidebar.repo_removed.connect(self._on_repo_removed)
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

    # ── shortcuts ──

    def _install_shortcuts(self) -> None:
        """Window-level QActions for Preferences / Add Repo / Quit.

        These used to live in a File menu. The top bar is now icon-only, so
        the actions are bound directly to the window — shortcuts still work,
        just with no menu surface.
        """
        for text, seq, slot in (
            ("Preferences", QKeySequence("Ctrl+,"), self._open_preferences),
            ("Add Repo",    QKeySequence("Ctrl+O"), self._sidebar._on_add_clicked),
            ("Quit",        QKeySequence.Quit,     self.close),
        ):
            act = QAction(text, self)
            act.setShortcut(seq)
            act.setShortcutContext(Qt.ApplicationShortcut)
            act.triggered.connect(slot)
            self.addAction(act)

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
        self._sidebar_save_timer.start()  # restart resets the 300ms window

    def _persist_settings_now(self) -> None:
        try:
            save_settings(self._settings)
        except OSError as e:
            log.warning("could not persist settings: %s", e)

    def _open_preferences(self) -> None:
        dlg = PreferencesDialog(self._settings, self)
        dlg.applied.connect(self._on_settings_changed)
        dlg.exec()

    def _on_settings_changed(self, settings: Settings) -> None:
        # Keep the reference in sync so new terminal spawns pick it up.
        self._settings = settings

        # Re-apply sidebar side / width — cheap, and the only way the user
        # sees their UI-tab edits without restarting.
        self._apply_sidebar_layout()
        self._sidebar.set_badge_style(settings.ui.status_badge_style)

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

    def _on_repo_removed(self, path: str) -> None:
        """A repo was removed from the sidebar — also tear down its terminal."""
        self._working.discard(_norm_path(path))
        host = self._terminals.pop(path, None)
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
        host = self._terminals.pop(repo.path, None)
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
        cur = self._current_repo_path()
        cur_row = model.index_of(cur) if cur else -1
        next_row = (cur_row + delta) % n
        repo = model.repo_at(next_row)
        if repo is not None:
            self._sidebar.select_path(repo.path)

    # ── terminal context menu ──

    def _on_terminal_context_menu(self, repo: Repo, global_pos) -> None:
        """Right-click-in-terminal menu: Paste, Reload, Prefs, plus a
        disabled hint row pointing at Ctrl+Shift+C for Copy (xterm owns the
        selection so only it can write it to the clipboard)."""
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)

        paste_act = QAction("Paste", menu)
        paste_act.setToolTip("Send clipboard text to the terminal (Ctrl+Shift+V)")
        paste_act.triggered.connect(lambda _=False, r=repo: self._paste_clipboard_to(r))
        menu.addAction(paste_act)

        copy_hint = QAction("Copy selection   Ctrl+Shift+C", menu)
        copy_hint.setEnabled(False)
        menu.addAction(copy_hint)

        menu.addSeparator()

        reload_act = QAction("Reload terminal", menu)
        reload_act.triggered.connect(lambda _=False, r=repo: self._sidebar._confirm_reload(r))
        menu.addAction(reload_act)

        prefs_act = QAction("Preferences…", menu)
        prefs_act.triggered.connect(self._open_preferences)
        menu.addAction(prefs_act)

        menu.exec(global_pos)

    def _paste_clipboard_to(self, repo: Repo) -> None:
        from PySide6.QtWidgets import QApplication
        host = self._terminals.get(repo.path)
        if host is None:
            return
        host.paste_text(QApplication.clipboard().text())

    # ── helpers ──

    def _make_empty_placeholder(self) -> QWidget:
        w = QWidget(self)
        w.setAutoFillBackground(True)
        return w

    def _ensure_terminal(self, repo: Repo) -> TerminalHost:
        """Lazy-spawn a TerminalHost for the given repo."""
        host = self._terminals.get(repo.path)
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
        host.cycle_repo_requested.connect(self._on_cycle_repo_requested)
        host.context_menu_requested.connect(
            lambda pos, r=repo: self._on_terminal_context_menu(r, pos)
        )
        self._terminals[repo.path] = host
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
        self._title.set_repo(repo.name, self._branch_for(repo.path))
        # _ensure_terminal handles setCurrentWidget on first spawn; for a
        # pre-existing host we still need to swap to it.
        host = self._ensure_terminal(repo)
        self._stack.setCurrentWidget(host)
        host.focus_child()
        # Persist so the violet dot can be restored next launch. Best-effort:
        # a write failure here shouldn't block the click.
        if self._settings.last_focused_repo != repo.path:
            self._settings.last_focused_repo = repo.path
            try:
                save_settings(self._settings)
            except OSError as e:
                log.warning("could not persist last_focused_repo: %s", e)

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

    def _on_terminal_failed(self, repo: Repo, msg: str) -> None:
        log.warning("terminal for %s failed: %s", repo.path, msg)
        QMessageBox.warning(self, f"xterm failed for {repo.name}", msg)

    def _on_terminal_finished(self, repo: Repo, code: int) -> None:
        self._working.discard(_norm_path(repo.path))
        self._sidebar.set_working(repo.path, False)
        host = self._terminals.pop(repo.path, None)
        was_current = host is not None and self._stack.currentWidget() is host
        if host is not None:
            self._stack.removeWidget(host)
            host.deleteLater()
        # If the departing terminal was visible, show the placeholder so we
        # don't silently switch to some other repo's terminal.
        if was_current:
            self._stack.setCurrentWidget(self._empty_placeholder)
        log.info("terminal for %s exited (code=%d)", repo.path, code)

    def _on_hook_event(self, obj: dict) -> None:
        event = str(obj.get("event", ""))
        payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
        cwd = obj.get("cwd") or (payload.get("cwd") if isinstance(payload, dict) else None)
        log.info(
            "hook event=%s cwd=%r matched_row=%s",
            event, cwd,
            self._sidebar.model.index_of(str(cwd)) if cwd else "no-cwd",
        )

        # Track Claude's mid-turn state. UserPromptSubmit means the user
        # just sent a prompt; Stop/Notification mean Claude is done or
        # waiting for input. Drives both the close-confirmation prompt and
        # the per-repo status badge in the sidebar.
        if cwd:
            cwd_key = _norm_path(str(cwd))
            if event == "UserPromptSubmit":
                self._working.add(cwd_key)
                # User just engaged this repo — clear any stale status dot
                # and start the spinner.
                self._sidebar.clear_status(str(cwd))
                self._sidebar.set_working(str(cwd), True)
                return
            if event in ("Stop", "Notification"):
                self._working.discard(cwd_key)
                self._sidebar.set_working(str(cwd), False)

        if event == "RepoAdded" and cwd:
            self._sidebar.model.add_repo(cwd)
            return

        if event in ("Stop", "Notification"):
            # Light the bell dot so the user has a glanceable "something
            # happened" signal even if the per-repo sidebar dot is off-screen.
            self._bell_btn.set_unseen(True)
            # Status dot on the sidebar — fires for every repo, including
            # the active one. Cleared on next UserPromptSubmit or when the
            # user re-clicks the row.
            if cwd and self._sidebar.model.index_of(str(cwd)) >= 0:
                from src.ui.repo_sidebar import STATUS_ATTENTION, STATUS_DONE
                status = STATUS_ATTENTION if event == "Notification" else STATUS_DONE
                self._sidebar.set_status(str(cwd), status)

    def _current_repo_path(self) -> str | None:
        w = self._stack.currentWidget()
        for path, host in self._terminals.items():
            if host is w:
                return path
        return None

    # ── lifecycle ──

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # Only nag when Claude is mid-turn somewhere — an idle shell sitting
        # at a prompt is fine to kill silently. Working state is tracked via
        # UserPromptSubmit / Stop / Notification hooks.
        # _working is keyed by realpath; _terminals is keyed by the raw
        # repo.path the sidebar handed us. Map back to the raw key so the
        # is_running check lines up.
        norm_to_raw = {_norm_path(k): k for k in self._terminals}
        working = [norm_to_raw[p] for p in self._working
                   if p in norm_to_raw and self._terminals[norm_to_raw[p]].is_running()]
        if working:
            names = ", ".join(os.path.basename(p.rstrip("/")) or p for p in working)
            ans = QMessageBox.question(
                self,
                "Quit ccwork?",
                f"Claude is working in {len(working)} repo(s): {names}.\n\n"
                "Quitting kills those sessions mid-response. The conversation "
                "transcripts are preserved — Claude will resume where it left "
                "off next launch — but any in-flight response is lost.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                event.ignore()
                return
        for host in list(self._terminals.values()):
            host.stop()
        self._terminals.clear()
        super().closeEvent(event)


class _BellButton(QToolButton):
    """🔔 toolbutton with a small red dot in the corner when unseen alerts exist."""

    DOT_COLOR = QColor(220, 80, 80)
    DOT_D = 7

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setText("🔔")
        self.setAutoRaise(True)
        self._unseen = False

    def set_unseen(self, on: bool) -> None:
        if on != self._unseen:
            self._unseen = on
            self.update()

    def paintEvent(self, ev) -> None:  # type: ignore[override]
        super().paintEvent(ev)
        if not self._unseen:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(self.DOT_COLOR)
        d = self.DOT_D
        p.drawEllipse(self.width() - d - 2, 2, d, d)
