"""TerminalLifecycle — bookkeeping for the QStackedWidget of TerminalHosts.

Owns the `repo.id → TerminalHost` mapping and the spawn/dispose/reload
sequence that used to live in MainWindow. MainWindow keeps the
higher-level concerns (working-set, title bar, placeholder swap on
disposal-of-current) and connects to this object's signals.

This split exists because the host bookkeeping was duplicated three
times in MainWindow (`_on_repo_removed`, `_reload_terminal`,
`_on_terminal_finished`) and per-session routing (REFACTORING.md 1.2)
made it the natural seam to harden.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtWidgets import QStackedWidget

from src.core.repo_store import Repo
from src.core.settings import Settings
from src.core.terminal_session import build_session
from src.ui.terminal_host import TerminalHost


class TerminalLifecycle(QObject):
    """One TerminalHost per repo.id; centralizes spawn/dispose/reload."""

    # Re-emitted from TerminalHost so MainWindow can connect to one source
    # of truth instead of every spawn re-wiring 5 lambdas. Each carries the
    # owning Repo so the slot doesn't need to keep its own id→repo lookup.
    failed = Signal(Repo, str)
    finished = Signal(Repo, int)  # repo, exit_code
    zoom_requested = Signal(int)
    cycle_repo_requested = Signal(int)
    context_menu_requested = Signal(Repo, QPoint)

    def __init__(
        self,
        stack: QStackedWidget,
        sidebar,  # RepoSidebar — typed as Any to avoid circular import
        settings_provider: Callable[[], Settings],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._stack = stack
        self._sidebar = sidebar
        self._settings_provider = settings_provider
        self._terminals: dict[str, TerminalHost] = {}

    # ── public API ──

    def ensure(self, repo: Repo) -> TerminalHost:
        """Lazy-spawn a TerminalHost for `repo` and make it current."""
        host = self._terminals.get(repo.id)
        if host is not None:
            self._stack.setCurrentWidget(host)
            return host
        spec = build_session(repo, xterm_settings=self._settings_provider().xterm)
        host = TerminalHost(
            argv=spec.argv,
            env=spec.env,
            cwd=spec.cwd,
            parent=self._stack,
        )
        host.failed.connect(lambda msg, r=repo: self.failed.emit(r, msg))
        host.finished.connect(lambda code, r=repo: self.finished.emit(r, code))
        host.zoom_requested.connect(self.zoom_requested.emit)
        host.cycle_repo_requested.connect(self.cycle_repo_requested.emit)
        host.context_menu_requested.connect(
            lambda pos, r=repo: self.context_menu_requested.emit(r, pos)
        )
        self._terminals[repo.id] = host
        self._sidebar.set_terminal_active(repo.id, True)
        self._stack.addWidget(host)
        # Map the parent X window before xterm reparents into it.
        self._stack.setCurrentWidget(host)
        host.start()
        return host

    def dispose(self, repo_id: str, *, stop: bool = True) -> bool:
        """Tear down the host for `repo_id`. Returns True if the disposed
        host was the currently visible widget — the caller decides what
        placeholder to swap to.

        `stop=False` skips the explicit host.stop() — used when xterm
        already exited on its own.
        """
        host = self._terminals.pop(repo_id, None)
        if host is None:
            return False
        was_current = self._stack.currentWidget() is host
        self._stack.removeWidget(host)
        if stop:
            host.stop()
        host.deleteLater()
        return was_current

    def reload(self, repo: Repo) -> TerminalHost:
        """Dispose any existing host and spawn a fresh one with current settings."""
        self.dispose(repo.id)
        return self.ensure(repo)

    def get(self, repo_id: str) -> TerminalHost | None:
        return self._terminals.get(repo_id)

    def current_repo_id(self) -> str | None:
        """The id whose host is currently visible in the stack, or None."""
        w = self._stack.currentWidget()
        for repo_id, host in self._terminals.items():
            if host is w:
                return repo_id
        return None

    def hosts(self) -> Iterable[TerminalHost]:
        return self._terminals.values()

    def shutdown(self) -> None:
        """Stop every running host and clear the map. For closeEvent."""
        for host in list(self._terminals.values()):
            host.stop()
        self._terminals.clear()

    def __contains__(self, repo_id: str) -> bool:
        return repo_id in self._terminals
