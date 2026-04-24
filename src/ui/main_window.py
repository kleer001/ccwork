"""MainWindow — the top-level Qt layout.

Structure:

    ┌──────────────────────────────────────────────────────────┐
    │ TitleLabel  ................................  AlertsPanel│  ← title strip
    ├──────────┬───────────────────────────────────────────────┤
    │          │                                               │
    │  Repo    │              Terminal stack                   │
    │ Sidebar  │   (one TerminalHost per repo, swapped         │
    │          │    by QStackedWidget on selection)            │
    │          │                                               │
    └──────────┴───────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.hook_server import HookServer
from src.core.repo_store import Repo, RepoStore
from src.core.settings import Settings
from src.core.terminal_session import build_session
from src.ui.alerts_panel import AlertEntry, AlertsPanel
from src.ui.preferences_dialog import PreferencesDialog
from src.ui.qt_theme import apply_theme
from src.ui.repo_sidebar import RepoSidebar
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

        # ── top strip ──
        self._title = TitleLabel(self)
        self._alerts = AlertsPanel(self)
        top = QWidget(self)
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(6)
        top_lay.addWidget(self._title, 1)
        top_lay.addWidget(self._alerts, 0)
        top.setMaximumHeight(140)

        # ── body: sidebar + terminal stack ──
        self._sidebar = RepoSidebar(self._store, self)
        self._stack = QStackedWidget(self)
        self._empty_placeholder = self._make_empty_placeholder()
        self._stack.addWidget(self._empty_placeholder)
        self._stack.setCurrentWidget(self._empty_placeholder)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 1000])

        # ── assemble ──
        central = QWidget(self)
        v = QVBoxLayout(central)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)
        v.addWidget(top)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        v.addWidget(sep)
        v.addWidget(splitter, 1)
        self.setCentralWidget(central)

        # ── menu bar ──
        self._build_menu_bar()

        # ── wiring ──
        self._sidebar.repo_selected.connect(self._on_repo_selected)
        self._sidebar.repo_added.connect(self._on_repo_added)
        self._sidebar.reload_requested.connect(self._reload_terminal)
        self._sidebar.repo_removed.connect(self._on_repo_removed)
        self._hook_server.event_received.connect(self._on_hook_event)

    # ── menu ──

    def _build_menu_bar(self) -> None:
        mb = self.menuBar()
        mb.setNativeMenuBar(False)  # keep the bar inside our window on all DEs

        file_menu = mb.addMenu("&File")
        prefs_action = QAction("&Preferences…", self)
        prefs_action.setShortcut(QKeySequence("Ctrl+,"))
        prefs_action.triggered.connect(self._open_preferences)
        file_menu.addAction(prefs_action)

        add_repo = QAction("&Add Repo…", self)
        add_repo.setShortcut(QKeySequence("Ctrl+O"))
        add_repo.triggered.connect(self._sidebar._on_add_clicked)
        file_menu.addAction(add_repo)

        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _open_preferences(self) -> None:
        dlg = PreferencesDialog(self._settings, self)
        dlg.applied.connect(self._on_settings_changed)
        dlg.exec()

    def _on_settings_changed(self, settings: Settings) -> None:
        # Keep the reference in sync so new terminal spawns pick it up.
        self._settings = settings

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
        host = self._terminals.pop(path, None)
        if host is not None:
            was_current = self._stack.currentWidget() is host
            self._stack.removeWidget(host)
            host.stop()
            host.deleteLater()
            if was_current:
                self._stack.setCurrentWidget(self._empty_placeholder)
                self._title.set_repo(None)

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
        self._terminals[repo.path] = host
        self._stack.addWidget(host)
        # Make the host current + visible BEFORE starting xterm so the parent
        # X window is mapped when xterm reparents into it.
        self._stack.setCurrentWidget(host)
        host.start()
        return host

    # ── slots ──

    def _on_repo_selected(self, repo: Repo) -> None:
        self._title.set_repo(repo.name)
        # _ensure_terminal handles setCurrentWidget on first spawn; for a
        # pre-existing host we still need to swap to it.
        host = self._ensure_terminal(repo)
        self._stack.setCurrentWidget(host)
        # Refresh branch subtitle when user focuses a repo (cheap git call).
        self._sidebar.refresh_branches()

    def _on_repo_added(self, repo: Repo) -> None:
        self._sidebar.refresh_branches()
        self._alerts.add_alert(AlertEntry(
            event="RepoAdded",
            repo_name=repo.name,
            message=repo.path,
            ts=time.time(),
        ))

    def _on_terminal_failed(self, repo: Repo, msg: str) -> None:
        log.warning("terminal for %s failed: %s", repo.path, msg)
        QMessageBox.warning(self, f"xterm failed for {repo.name}", msg)

    def _on_terminal_finished(self, repo: Repo, code: int) -> None:
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
        ts = float(obj.get("ts") or time.time())

        if event == "RepoAdded" and cwd:
            if self._sidebar.model.add_repo(cwd):
                self._alerts.add_alert(AlertEntry(
                    event="RepoAdded",
                    repo_name=os.path.basename(str(cwd).rstrip("/")) or str(cwd),
                    message=str(cwd),
                    ts=ts,
                ))
            return

        if event in ("Stop", "Notification"):
            repo_name = os.path.basename(str(cwd).rstrip("/")) if cwd else "?"
            msg = _short_message(event, payload)
            self._alerts.add_alert(AlertEntry(event=event, repo_name=repo_name, message=msg, ts=ts))
            # Bump unread for the matching repo, if we know it and it's not
            # the one the user is currently looking at.
            if cwd:
                row = self._sidebar.model.index_of(str(cwd))
                if row >= 0:
                    repo = self._sidebar.model.repo_at(row)
                    if repo is not None and self._current_repo_path() != repo.path:
                        self._sidebar.bump_unread(repo.path)

    def _current_repo_path(self) -> str | None:
        w = self._stack.currentWidget()
        for path, host in self._terminals.items():
            if host is w:
                return path
        return None

    # ── lifecycle ──

    def closeEvent(self, event) -> None:  # type: ignore[override]
        for host in list(self._terminals.values()):
            host.stop()
        self._terminals.clear()
        super().closeEvent(event)


def _short_message(event: str, payload: dict) -> str:
    """Extract a one-line description from a hook payload."""
    if not isinstance(payload, dict):
        return event
    # Claude Code's Notification hook typically has {"message": ...}.
    msg = payload.get("message")
    if isinstance(msg, str) and msg:
        return msg
    if event == "Stop":
        return "task done"
    if event == "Notification":
        return "needs your input"
    return event
