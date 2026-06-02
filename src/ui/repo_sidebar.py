"""Left-hand repo list widget: scrollable rows + '+ Add Repo' button.

`RepoSidebar` wires a `QListView` to `RepoListModel` and `RepoDelegate`,
owns the spinner / auto-arrange-walk timers and the sidebar-quiet gate, and
hosts the row context menu and badge picker. The model, delegate, role
constants, and status values are re-exported from this module so existing
imports (`from src.ui.repo_sidebar import RepoListModel, ROLE_*, STATUS_*`)
keep working.
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import time

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPoint,
    QProcess,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core import repo_store
from src.core.hook_server import (
    EVENT_NOTIFICATION,
    EVENT_STOP,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore
# Re-exported as this module's public surface: external code and tests import
# the model, delegate, roles, status values, and `_format_elapsed` from
# `src.ui.repo_sidebar`.
from src.ui.badge_theme import STATUS_ATTENTION, STATUS_DONE
from src.ui.repo_delegate import RepoDelegate
from src.ui.repo_model import (
    ROLE_BRANCH,
    ROLE_HAS_TERMINAL,
    ROLE_LAST_FOCUSED,
    ROLE_PATH_MISSING,
    ROLE_REPO,
    ROLE_SESSION_ACTIVE,
    ROLE_STATUS,
    ROLE_SUBAGENTS,
    ROLE_WORKING,
    RepoListModel,
    _CLAUDE_STATE_EVENTS,
    _format_elapsed,
)


log = logging.getLogger(__name__)


# 25 glyphs commonly used to tag software-project work. Click-to-pick in
# the badge dialog; not exhaustive — the line edit accepts any character.
BADGE_GALLERY = (
    "🐛", "🧪", "🚀", "🔧", "🎨",
    "📦", "🔥", "⚡", "✨", "📝",
    "🔒", "🌟", "🏗️", "🎯", "🔍",
    "💡", "⚙️", "🐳", "🌿", "🔬",
    "🛠️", "📊", "🧹", "🗃️", "🎬",
)

# External one-shot emoji pickers tried in order. First found wins; the
# rest depend on the user's desktop. Fallback path is the line edit's own
# OS-level shortcut (Ctrl+. / Ctrl+;).
EMOJI_PICKER_CANDIDATES = (
    "bemoji", "rofimoji", "gnome-characters", "gucharmap", "kcharselect",
)


def _find_emoji_picker() -> str | None:
    for cmd in EMOJI_PICKER_CANDIDATES:
        path = shutil.which(cmd)
        if path:
            return path
    return None


class RepoSidebar(QWidget):
    """The left-hand column: scrollable repo list + '+ Add Repo' at the bottom."""

    repo_selected = Signal(Repo)
    repo_added = Signal(Repo)
    repo_removed = Signal(Repo)  # emits the removed Repo (id needed to tear down)
    reload_requested = Signal(Repo)  # user asked to respawn the terminal
    # Emitted after the user picks "Copy path" — carries the path that just
    # landed on the clipboard so MainWindow can flash a status-bar
    # confirmation. The sidebar doesn't own a status bar; this keeps it
    # display-agnostic.
    path_copied = Signal(str)

    def __init__(self, store: RepoStore, parent=None, settings=None) -> None:
        super().__init__(parent)
        self._store = store
        self._settings = settings
        # Resolve animation knobs once; fall back to defaults when called
        # without settings (some test paths do this).
        from src.core.settings import AnimationSettings
        self._anim = (
            settings.ui.animation if settings is not None
            else AnimationSettings()
        )
        self._model = RepoListModel(store, self)

        self._view = QListView(self)
        self._view.setModel(self._model)
        layout_cfg = settings.ui.layout if settings is not None else None
        self._delegate = RepoDelegate(self._view, layout=layout_cfg)
        self._view.setItemDelegate(self._delegate)

        # Braille-spinner ticker. Only runs while at least one repo is in
        # the "working" state — otherwise it would repaint the viewport 10×
        # per second for no reason.
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(self._anim.spinner_interval_ms)
        self._spinner_timer.timeout.connect(self._advance_spinner)
        # Debounced auto-arrange. Restarted on every Claude-driven event
        # while ui.auto_arrange_repos is True; fires once after the
        # configured reorder_debounce_ms of quiet to avoid reshuffling
        # under the user's eye.
        self._reorder_timer = QTimer(self)
        self._reorder_timer.setSingleShot(True)
        self._reorder_timer.setInterval(self._anim.reorder_debounce_ms)
        self._reorder_timer.timeout.connect(self._apply_auto_arrange)
        # Quiet-window gate for the bubble walk. The walk fires only when
        # the sidebar has had no input (mouse, key, selection) for
        # the configured sidebar_quiet_ms. While the user is hovering, scrolling, or
        # picking a repo, _bump_activity() pushes the timestamp forward
        # and pending walks keep deferring; while they're typing in
        # xterm, no Qt events reach the sidebar so the timestamp
        # naturally ages and queued walks fire. _check_pending_walk
        # re-runs itself on _arrange_check_timer until the quiet
        # condition is met or the pending state is cleared.
        # Initial 0.0 lets the very first trigger fire immediately —
        # there's no genuine sidebar activity at startup.
        self._last_sidebar_activity = 0.0
        self._arrange_pending = False
        self._arrange_check_timer = QTimer(self)
        self._arrange_check_timer.setSingleShot(True)
        self._arrange_check_timer.timeout.connect(self._check_pending_walk)
        # Stepwise bubble-up: each tick swaps one adjacent pair toward the
        # composed target order (auto-arrange ⊕ grouping, whichever prefs
        # are on). Self-correcting — if a new active repo or a fresh
        # activity event arrives mid-animation, the next tick sees the
        # updated target and keeps walking. Stops when current == target.
        # Per-tick interval is recomputed by _step_arrange along a sine
        # ease-in-out curve, so the constructor default is a placeholder.
        self._arrange_step_timer = QTimer(self)
        self._arrange_step_timer.setInterval(self._anim.arrange_step_max_ms)
        self._arrange_step_timer.timeout.connect(self._step_arrange)
        # Resets at every walk start. Drives the easing curve.
        self._arrange_steps_taken = 0
        self._view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._view.setSelectionMode(QAbstractItemView.SingleSelection)
        # Per-row sizeHint: the group-boundary row is taller than the rest
        # to make room for the inter-group gap. Uniform sizes would skip the
        # delegate's per-index sizeHint call entirely.
        self._view.setUniformItemSizes(False)
        # Mirror the initial pref into the delegate so the first paint after
        # construction already shows the right grouping behavior.
        if settings is not None:
            self._delegate.group_enabled = bool(
                getattr(settings.ui, "group_active_repos", False)
            )
        self._view.selectionModel().currentChanged.connect(self._on_current_changed)
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        # Mouse tracking + event filter: catches hover-without-click so
        # we know the cursor is over the sidebar even before any button
        # is pressed. Without setMouseTracking, MouseMove fires only
        # while a button is held.
        self._view.setMouseTracking(True)
        self._view.viewport().setMouseTracking(True)
        self._view.installEventFilter(self)
        self._view.viewport().installEventFilter(self)

        self._add_btn = QPushButton("+ Add Repo", self)
        self._add_btn.clicked.connect(self.add_repo_via_dialog)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._view, 1)
        lay.addWidget(self._add_btn, 0)

        # Allow the splitter to drag the sidebar narrow. The status badge is
        # always reserved when present; text elides to fit.
        self.setMinimumWidth(60)
        self.setMaximumWidth(320)

        self._model.reload()
        self._model.refresh_branches()

    # ── public API ──

    @property
    def model(self) -> RepoListModel:
        return self._model

    def select_path(self, path: str) -> None:
        row = self._model.index_of(path)
        if row >= 0:
            idx = self._model.index(row)
            self._view.setCurrentIndex(idx)

    def select_id(self, repo_id: str) -> None:
        row = self._model.index_of_id(repo_id)
        if row >= 0:
            idx = self._model.index(row)
            self._view.setCurrentIndex(idx)

    def refresh_branches(self) -> None:
        self._model.refresh_branches()

    def set_status(self, path: str, status: str) -> None:
        self._model.set_status(path, status)
        if status in (STATUS_DONE, STATUS_ATTENTION):
            self._maybe_schedule_reorder()

    def clear_status(self, path: str) -> None:
        self._model.clear_status(path)

    def set_last_focused(self, path: str) -> None:
        self._model.set_last_focused(path)

    def set_settings(self, settings) -> None:
        """Swap in a fresh Settings reference (called after Preferences edits)."""
        self._settings = settings
        new_group = bool(getattr(settings.ui, "group_active_repos", False))
        if self._delegate.group_enabled != new_group:
            self._delegate.group_enabled = new_group
            # Re-apply grouping so rows already shift; if turning OFF, the
            # current order is preserved (we never auto-revert) but the gap
            # disappears. Either way, sizeHints must be re-queried.
            if new_group:
                self._model.apply_terminal_grouping()
            self._view.scheduleDelayedItemsLayout()
            self._view.viewport().update()

    def set_terminal_active(self, repo_id: str, active: bool) -> None:
        """Mark a row as having a live terminal and queue a re-group.

        We deliberately do NOT reshuffle right now: the row whose terminal
        just spawned is the row the user just clicked, and yanking it out
        from under the cursor reads as "the wrong repo got selected." The
        focus gate (_terminal_focused) defers until the user has actually
        engaged with a terminal; until then this just queues via
        _maybe_walk(). Same applies on terminal close.
        """
        self._model.set_terminal_active(repo_id, active)
        if self._settings is not None and getattr(
            self._settings.ui, "group_active_repos", False
        ):
            self._maybe_walk()
        # Boundary may have shifted (or the bold/italic font flipped) —
        # re-query sizeHints. No reorder yet.
        self._view.scheduleDelayedItemsLayout()

    def _bump_activity(self) -> None:
        """Mark the sidebar as just-touched. Pushes the quiet-window
        deadline forward so any pending walk keeps deferring."""
        self._last_sidebar_activity = time.monotonic()

    # Activity sources we care about. Hover/move catches "cursor is on
    # the sidebar" even without a click, which is the visual state that
    # made the original yank-under-cursor problem feel wrong.
    _ACTIVITY_EVENTS = frozenset({
        QEvent.MouseMove,
        QEvent.MouseButtonPress,
        QEvent.Enter,
        QEvent.HoverEnter,
        QEvent.HoverMove,
        QEvent.KeyPress,
        QEvent.Wheel,
        QEvent.FocusIn,
    })

    def eventFilter(self, obj, event):  # type: ignore[override]
        if event.type() in self._ACTIVITY_EVENTS and (
            obj is self._view or obj is self._view.viewport()
        ):
            self._bump_activity()
        return super().eventFilter(obj, event)

    def set_badge_style(self, style: str) -> None:
        """Switch between the colored dot and single-glyph badge."""
        if style not in ("dot", "glyph"):
            return
        if self._delegate.badge_style == style:
            return
        self._delegate.badge_style = style
        self._view.viewport().update()

    def set_working(self, path: str, working: bool) -> None:
        self._model.set_working(path, working)
        self._refresh_spinner_timer()
        if working:
            self._maybe_schedule_reorder()

    def clear_session(self, path: str) -> None:
        self._model.clear_session(path)
        self._refresh_spinner_timer()

    def apply_hook_event(
        self, event: str, path: str, payload: dict | None = None
    ) -> None:
        """Single entry point for a Claude hook event affecting one path.

        Delegates state mutation to the model and refreshes UI side-effects
        (spinner timer + auto-arrange schedule). MainWindow._on_hook_event
        is a thin dispatcher over this method.

        `payload` is only inspected for PreToolUse (to distinguish
        background subagent dispatches from other tool calls). The other
        events drive transitions on event-name alone.
        """
        if event not in _CLAUDE_STATE_EVENTS:
            return
        self._model.apply_hook_event(event, path, payload)
        self._refresh_spinner_timer()
        # Only the three turn-level events feed the activity sort. Bg-agent
        # dispatch / stop should not bump the auto-arrange schedule —
        # otherwise long-running background work would keep reshuffling
        # the sidebar under the user's eye.
        if event in (EVENT_USER_PROMPT_SUBMIT, EVENT_STOP, EVENT_NOTIFICATION):
            self._maybe_schedule_reorder()

    def _refresh_spinner_timer(self) -> None:
        """Start the spinner ticker when any row needs animation; stop otherwise.

        Two independent triggers: a live working spinner OR a live
        subagent twinkle. Both share the same `spinner_frame` counter on
        the delegate, so one timer drives both animations and we don't
        pay double the repaint cost.
        """
        if self._model.any_working() or self._model.any_subagents():
            if not self._spinner_timer.isActive():
                self._spinner_timer.start()
        else:
            self._spinner_timer.stop()

    def _maybe_schedule_reorder(self) -> None:
        if self._settings is None:
            return
        if not getattr(self._settings.ui, "auto_arrange_repos", False):
            return
        # QTimer.start() restarts an active single-shot timer — exactly
        # the debounce we want.
        self._reorder_timer.start()

    def _apply_auto_arrange(self) -> None:
        # Pref may have flipped off during the 2 s window — bail.
        if self._settings is None:
            return
        if not getattr(self._settings.ui, "auto_arrange_repos", False):
            return
        self._maybe_walk()

    def _maybe_walk(self) -> None:
        """Start the bubble walk if the sidebar is quiet; else defer.

        Single chokepoint for both auto-arrange and terminal-grouping
        triggers. The defer-and-recheck loop ensures the walk only runs
        when the user has been clearly off the sidebar for a moment —
        typically while typing in their terminal.
        """
        self._arrange_pending = True
        self._check_pending_walk()

    def _check_pending_walk(self) -> None:
        """Try to fire a pending walk. If the sidebar isn't quiet yet,
        re-arm the timer for when the quiet window would next elapse.
        """
        if not self._arrange_pending:
            return
        elapsed_ms = (time.monotonic() - self._last_sidebar_activity) * 1000
        if elapsed_ms >= self._anim.sidebar_quiet_ms:
            self._arrange_pending = False
            self._start_arrange_animation()
            return
        # Re-check exactly when the quiet window would close, plus a
        # small buffer so timer jitter can't undershoot.
        self._arrange_check_timer.start(int(self._anim.sidebar_quiet_ms - elapsed_ms) + 10)

    def _start_arrange_animation(self) -> None:
        """Walk one row toward the target order now, then keep ticking on
        the timer. No-op if already at target. Idempotent — if the timer
        is already running, it just keeps going (and naturally absorbs any
        new target, since each tick recomputes).
        """
        if self._arrange_step_timer.isActive():
            return
        # New walk — reset the step counter so the easing curve restarts
        # from the slow-start endpoint.
        self._arrange_steps_taken = 0
        # Step once now so the user sees motion immediately, not after a
        # 220 ms gap (the eye reads "trigger → motion" as causal).
        if self._step_arrange():
            self._arrange_step_timer.start()

    def _step_arrange(self) -> bool:
        """Advance one adjacent swap toward the composed target. Returns
        True if more work remains; False once converged (and stops timer).
        """
        if self._settings is None:
            self._arrange_step_timer.stop()
            return False
        target = self._model.target_order_ids(
            auto_arrange=bool(getattr(self._settings.ui, "auto_arrange_repos", False)),
            group_active=bool(getattr(self._settings.ui, "group_active_repos", False)),
        )
        current = [
            self._model.repo_at(i).id for i in range(self._model.rowCount())
        ]
        if current == target:
            self._arrange_step_timer.stop()
            return False
        for i, (cur_id, tgt_id) in enumerate(zip(current, target)):
            if cur_id == tgt_id:
                continue
            # The id that *should* sit at row i is currently lower; bubble
            # it up by one. Topmost mismatch wins so rows settle from the
            # top down — visually, the highest-priority repo finishes
            # first, then the next, etc.
            src_row = current.index(tgt_id)
            self._model.move_row_up(src_row)
            self._arrange_steps_taken += 1
            self._arrange_step_timer.setInterval(self._next_step_interval(target))
            return True
        self._arrange_step_timer.stop()
        return False

    def _next_step_interval(self, target: list[str]) -> int:
        """Sine ease-in-out cadence between swaps.

        After each swap we estimate total = swaps_done + remaining_swaps,
        then map the gap-to-next-swap onto sin(pi · x). x = 0 (first gap)
        and x = 1 (last gap) both give MAX (slow); x = 0.5 gives MIN
        (fast middle). The estimate floats — if a new active repo arrives
        mid-walk, total grows and the curve smoothly extends rather than
        snapping to a new ramp.
        """
        remaining = self._simulate_remaining_swaps(target)
        total = self._arrange_steps_taken + remaining
        max_ms = self._anim.arrange_step_max_ms
        min_ms = self._anim.arrange_step_min_ms
        if total <= 2:
            # 1 or 2 swaps total: too few for a meaningful curve. Slow &
            # deliberate reads better than abrupt.
            return max_ms
        gap_index = self._arrange_steps_taken - 1  # gap that follows this swap
        last_gap_index = total - 2
        # Clamp at 1.0: on the converging swap, gap_index can momentarily
        # exceed last_gap_index (the timer is about to be stopped anyway).
        x = min(1.0, gap_index / last_gap_index)
        eased = math.sin(math.pi * x)  # 0 at endpoints, 1 in middle
        # round (not int) to absorb sin(π) ≈ 1.22e-16 float drift at the
        # x=1.0 endpoint — int() would truncate to MAX-1 instead of MAX.
        return round(
            max_ms - (max_ms - min_ms) * eased
        )

    def _simulate_remaining_swaps(self, target: list[str]) -> int:
        """Replay the bubble-up algorithm on a copy of the current order
        and count swaps until convergence. A simple mismatch count over-
        estimates: when one id bubbles past several others, every row in
        between is "wrong" right now but resolves implicitly. The sim
        gives the exact number of move_row_up calls remaining.
        """
        current = [
            self._model.repo_at(j).id for j in range(self._model.rowCount())
        ]
        swaps = 0
        while current != target:
            for i, (c, t) in enumerate(zip(current, target)):
                if c == t:
                    continue
                src = current.index(t)
                current[src - 1], current[src] = current[src], current[src - 1]
                swaps += 1
                break
            else:
                break  # nothing to swap (shouldn't happen if current != target)
        return swaps

    def _advance_spinner(self) -> None:
        self._delegate.spinner_frame += 1
        # Repaint rows that are working OR have a live subagent twinkle —
        # both animations share spinner_frame, so any animated row needs an
        # update each tick. Untouched rows stay quiet.
        for row in range(self._model.rowCount()):
            idx = self._model.index(row)
            if idx.data(ROLE_WORKING) or (idx.data(ROLE_SUBAGENTS) or 0) > 0:
                self._view.update(idx)

    # ── signals ──

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        # Selection change is a strong "user is on the sidebar" signal —
        # arguably stronger than mouse hover. Push the quiet deadline.
        self._bump_activity()
        # Mark the row we're leaving as "last focused" so the user can spot
        # where they were before. Subject to priority rules in
        # RepoListModel.set_last_focused — won't overwrite Stop/Notification.
        prev_repo = self._model.repo_at(previous.row()) if previous.isValid() else None
        if prev_repo is not None:
            self._model.set_last_focused(prev_repo.path)
        repo = self._model.repo_at(current.row()) if current.isValid() else None
        if repo is not None:
            self._model.clear_status(repo.path)
            self.repo_selected.emit(repo)

    def add_repo_via_dialog(self) -> None:
        """Prompt the user for a directory and add it as a sidebar row.

        Public API — bound to the `+ Add Repo` button click and to the
        ``Ctrl+Shift+O`` global shortcut. The leading-underscore
        ``_on_add_clicked`` name was an accident of history (the
        button's signal handler convention bled into the binding API).
        """
        path = QFileDialog.getExistingDirectory(self, "Add repo directory", os.path.expanduser("~"))
        if not path:
            return
        self._add_path(path)

    def _add_path(self, path: str) -> Repo:
        """Append a row for `path`, select it, emit repo_added. Returns the new Repo."""
        added = self._model.add_repo(path)
        # Select the just-added row by id (path may be ambiguous now that
        # duplicates are allowed).
        row = self._model.index_of_id(added.id)
        if row >= 0:
            self._view.setCurrentIndex(self._model.index(row))
        self.repo_added.emit(added)
        return added

    def _on_context_menu(self, pos: QPoint) -> None:
        self._bump_activity()
        idx = self._view.indexAt(pos)
        if not idx.isValid():
            return
        repo = self._model.repo_at(idx.row())
        if repo is None:
            return
        menu = self._build_context_menu(repo, idx.row())
        menu.exec(self._view.viewport().mapToGlobal(pos))

    def _build_context_menu(self, repo: Repo, row: int) -> QMenu:
        """Construct the row right-click menu. Split out from
        ``_on_context_menu`` so tests can inspect actions (enabled state,
        tooltips, ordering) without simulating an actual right-click."""
        menu = QMenu(self)

        reload_act = QAction("Reload terminal", menu)
        reload_act.setToolTip("Respawn xterm to pick up new settings. Loses in-flight shell state.")
        reload_act.triggered.connect(lambda _=False, r=repo: self._confirm_reload(r))
        menu.addAction(reload_act)

        clone_act = QAction("Clone this repo", menu)
        clone_act.setToolTip("Add a second sidebar row pointing at the same directory (parallel session).")
        clone_act.triggered.connect(lambda _=False, r=repo: self._add_path(r.path))
        menu.addAction(clone_act)

        # Path-action group: no separator before, to read as one "things you
        # can do with this path" cluster alongside Clone. The existing
        # separator below fences off the cosmetic badge items.
        open_fm_act = QAction("Open in file manager", menu)
        if shutil.which("xdg-open") is None:
            open_fm_act.setEnabled(False)
            open_fm_act.setToolTip(
                "xdg-open not found. Install the xdg-utils package."
            )
        else:
            open_fm_act.setToolTip(
                "Launches your desktop's default file manager at the repo directory."
            )
            open_fm_act.triggered.connect(
                lambda _=False, r=repo: self._open_in_file_manager(r)
            )
        menu.addAction(open_fm_act)

        copy_path_act = QAction("Copy path", menu)
        copy_path_act.setToolTip("Copy the absolute repo path to the clipboard.")
        copy_path_act.triggered.connect(lambda _=False, r=repo: self._copy_path(r))
        menu.addAction(copy_path_act)

        rebind_act = QAction("Rebind to…", menu)
        rebind_act.setToolTip(
            "Repoint this row at a different directory (e.g. after renaming "
            "the repo on disk). Must be a git working-tree root."
        )
        rebind_act.triggered.connect(lambda _=False, r=repo: self._on_rebind(r))
        menu.addAction(rebind_act)

        menu.addSeparator()
        set_badge_act = QAction("Set badge…", menu)
        set_badge_act.setToolTip("Prefix the row with a glyph (emoji or any single character).")
        set_badge_act.triggered.connect(lambda _=False, r=repo: self._prompt_badge(r))
        menu.addAction(set_badge_act)

        clear_badge_act = QAction("Clear badge", menu)
        clear_badge_act.setEnabled(bool(repo.emoji))
        clear_badge_act.triggered.connect(lambda _=False, r=repo: self._model.set_emoji(r.id, ""))
        menu.addAction(clear_badge_act)

        menu.addSeparator()
        remove_act = QAction("Remove from sidebar", menu)
        remove_act.triggered.connect(lambda _=False, r=repo, row=row: self._confirm_remove(r, row))
        menu.addAction(remove_act)

        return menu

    def _open_in_file_manager(self, repo: Repo) -> None:
        """Spawn xdg-open at repo.path. The menu's enabled-state probe at
        build time guarantees xdg-open is on PATH when this is reachable."""
        ok = QProcess.startDetached("xdg-open", [repo.path])
        if not ok:
            log.warning("xdg-open failed to launch for %s", repo.path)

    def _copy_path(self, repo: Repo) -> None:
        """Put `repo.path` on the system clipboard and notify MainWindow
        so it can flash a status-bar confirmation."""
        QGuiApplication.clipboard().setText(repo.path)
        self.path_copied.emit(repo.path)

    def _on_rebind(self, repo: Repo) -> None:
        """Folder picker → validation → mutator. Validation is git-root only
        (via repo_store.is_git_root) because the rest of ccwork assumes
        every row is a git working tree."""
        start_dir = (
            repo.path if os.path.isdir(repo.path)
            else os.path.dirname(repo.path) or os.path.expanduser("~")
        )
        picked = QFileDialog.getExistingDirectory(
            self, "Rebind repo to…", start_dir,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not picked:
            return
        if not repo_store.is_git_root(picked):
            QMessageBox.warning(
                self, "Not a git root",
                f"{picked}\n\nis not the top level of a git working tree. "
                "Pick the directory that contains the .git folder.",
            )
            return
        self._model.rebind_repo(repo.id, picked)

    def _prompt_badge(self, repo: Repo) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Set badge")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(f"Badge for {repo.display_name}:"))
        layout.addWidget(QLabel("Click a glyph below, or type/paste your own."))

        edit = QLineEdit(repo.emoji, dlg)

        # 5×5 click-to-pick gallery. Populates the line edit; OK confirms.
        gallery = QGridLayout()
        gallery.setSpacing(2)
        gallery_font = QFont()
        gallery_font.setPointSize(gallery_font.pointSize() + 4)
        for i, glyph in enumerate(BADGE_GALLERY):
            btn = QToolButton(dlg)
            btn.setText(glyph)
            btn.setFont(gallery_font)
            btn.setAutoRaise(True)
            btn.setFixedSize(36, 36)
            btn.clicked.connect(lambda _=False, g=glyph: edit.setText(g))
            gallery.addWidget(btn, i // 5, i % 5)
        layout.addLayout(gallery)

        # Custom-input row: line edit + system picker launcher.
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        picker = _find_emoji_picker()
        browse_btn = QPushButton("Browse system…", dlg)
        if picker is None:
            browse_btn.setEnabled(False)
            browse_btn.setToolTip(
                "No system emoji picker found. Install one of: "
                + ", ".join(EMOJI_PICKER_CANDIDATES)
            )
        else:
            browse_btn.setToolTip(
                f"Launches {os.path.basename(picker)}. "
                "Most pickers copy to the clipboard — paste here with Ctrl+V."
            )
            browse_btn.clicked.connect(lambda _=False, p=picker: QProcess.startDetached(p, []))
        row.addWidget(browse_btn)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        edit.setFocus()
        if dlg.exec() == QDialog.Accepted:
            self._model.set_emoji(repo.id, edit.text().strip())

    def _confirm_reload(self, repo: Repo) -> None:
        ans = QMessageBox.question(
            self,
            "Reload terminal",
            f"Respawn the terminal for {repo.display_name}?\n\n"
            "The running shell (and any active Claude session) will be killed. "
            "If Claude was mid-response, that response is lost — but the "
            "conversation transcript is preserved; run `claude --continue` "
            "to resume it.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            self.reload_requested.emit(repo)

    def _confirm_remove(self, repo: Repo, row: int) -> None:
        ans = QMessageBox.question(
            self,
            "Remove from sidebar",
            f"Remove {repo.display_name} from ccwork?\n\n"
            "The repo directory on disk is untouched — this only removes it "
            "from the sidebar list.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            self._model.remove_repo_at(row)
            self.repo_removed.emit(repo)
