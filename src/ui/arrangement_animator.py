"""ArrangementAnimator — debounce + quiet-window + bubble-walk timers.

Decoupled from RepoSidebar so the animation logic can be unit-tested
without a QListView, and so the sidebar widget can focus on rendering
and selection. The pure helpers (`count_bubble_swaps`,
`step_interval_ms`) are static — exercise them directly.

Trigger paths:

- **Activity-driven** (`schedule_reorder`): a Claude event came in.
  Debounce 2 s, then quiet-gate, then walk. Restarts on every event so
  rapid-fire activity doesn't reshuffle until the storm settles.
- **Direct** (`request_walk`): a non-debounced trigger such as a
  terminal-active toggle. Quiet-gate, then walk.

The walk itself is a per-tick adjacent-swap (`move_row_up`) toward the
composed target order. Tick interval is a sine ease-in-out — slow at
the endpoints, fast in the middle — over the total swap count, which
is computed once at walk start and refreshed only when the target
shifts mid-walk.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

# Per-tick gap when reordering the sidebar. Eased along a sine curve:
# MAX at the endpoints (slow ease-in to register the motion has started,
# slow ease-out to settle), MIN in the middle (zip through). Total walk
# time for ~5 swaps is ~620 ms.
ARRANGE_STEP_MIN_MS = 80
ARRANGE_STEP_MAX_MS = 220

# Bubble walks defer until the sidebar has been "quiet" for this long.
# XEmbed makes "is the user in the terminal" un-detectable from Qt
# directly (xterm keystrokes never reach the Qt event loop), so we
# invert the question: assume "user is engaged with terminal" iff the
# sidebar has not seen any input for SIDEBAR_QUIET_MS.
SIDEBAR_QUIET_MS = 800

# Activity-driven reorders wait this long after the last event before
# even checking the quiet window. Avoids shuffling under the user's
# eye during a rapid-fire stream of Claude hooks.
REORDER_DEBOUNCE_MS = 2000


def count_bubble_swaps(current: list[str], target: list[str]) -> int:
    """Inversion count between `current` and `target` — the exact number
    of `move_row_up` calls the topmost-mismatch bubble walk will make.
    Order-sensitive on the contents; a plain mismatch count overestimates.
    """
    pos = {tid: i for i, tid in enumerate(target)}
    swaps = 0
    for i, cur_id in enumerate(current):
        ti = pos.get(cur_id, i)
        for cur_j in current[i + 1 :]:
            tj = pos.get(cur_j, i)
            if tj < ti:
                swaps += 1
    return swaps


def step_interval_ms(steps_taken: int, total: int) -> int:
    """Sine ease-in-out cadence between swaps.

    Maps gap-to-next-swap onto sin(pi · x). x = 0 (first gap) and x = 1
    (last gap) both give MAX (slow); x = 0.5 gives MIN (fast middle).
    `total` is set at walk start and only refreshed when the target
    shifts, so the curve stays stable.
    """
    if total <= 2:
        return ARRANGE_STEP_MAX_MS
    gap_index = steps_taken - 1  # gap that follows this swap
    last_gap_index = total - 2
    # Clamp at 1.0: on the converging swap, gap_index can momentarily
    # exceed last_gap_index (the timer is about to be stopped anyway).
    x = min(1.0, gap_index / last_gap_index)
    eased = math.sin(math.pi * x)  # 0 at endpoints, 1 in middle
    # round (not int) to absorb sin(π) ≈ 1.22e-16 float drift at the
    # x=1.0 endpoint — int() would truncate to MAX-1 instead of MAX.
    return round(
        ARRANGE_STEP_MAX_MS - (ARRANGE_STEP_MAX_MS - ARRANGE_STEP_MIN_MS) * eased
    )


class ArrangementAnimator(QObject):
    """Three-timer state machine driving the sidebar reshuffle animation."""

    def __init__(
        self,
        model,  # RepoListModel — typed loosely to avoid circular import
        settings_provider: Callable[[], object | None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._settings_provider = settings_provider
        # Initial 0.0 lets the first trigger fire immediately — there's
        # no genuine sidebar activity at startup.
        self._last_activity = 0.0
        self._pending = False
        self._steps_taken = 0
        self._total_estimate = 0
        self._target_cache: list[str] = []

        self._reorder_timer = QTimer(self)
        self._reorder_timer.setSingleShot(True)
        self._reorder_timer.setInterval(REORDER_DEBOUNCE_MS)
        self._reorder_timer.timeout.connect(self._on_reorder_debounce_elapsed)

        self._check_timer = QTimer(self)
        self._check_timer.setSingleShot(True)
        self._check_timer.timeout.connect(self._check_pending)

        self._step_timer = QTimer(self)
        self._step_timer.setInterval(ARRANGE_STEP_MAX_MS)
        self._step_timer.timeout.connect(self._step)

    # ── public API ──

    def schedule_reorder(self) -> None:
        """Activity-driven path: debounce 2 s, then quiet-gated walk.

        QTimer.start() restarts an active single-shot timer — exactly the
        debounce we want for the activity stream.
        """
        if not self._auto_arrange_enabled():
            return
        self._reorder_timer.start()

    def request_walk(self) -> None:
        """Direct path: quiet-gated walk, no debounce.

        For triggers like terminal-active toggle that should react
        promptly but still respect the quiet window.
        """
        self._pending = True
        self._check_pending()

    def bump_activity(self) -> None:
        """Push the quiet-window deadline forward. Callers wire this to
        sidebar mouse/key/selection events."""
        self._last_activity = time.monotonic()

    # ── internal ──

    def _auto_arrange_enabled(self) -> bool:
        s = self._settings_provider()
        return bool(s and getattr(getattr(s, "ui", None), "auto_arrange_repos", False))

    def _group_enabled(self) -> bool:
        s = self._settings_provider()
        return bool(s and getattr(getattr(s, "ui", None), "group_active_repos", False))

    def _on_reorder_debounce_elapsed(self) -> None:
        # Pref may have flipped off during the 2 s window — bail.
        if not self._auto_arrange_enabled():
            return
        self.request_walk()

    def _check_pending(self) -> None:
        """Try to fire a pending walk. If the sidebar isn't quiet yet,
        re-arm the timer for when the quiet window would next elapse.
        """
        if not self._pending:
            return
        elapsed_ms = (time.monotonic() - self._last_activity) * 1000
        if elapsed_ms >= SIDEBAR_QUIET_MS:
            self._pending = False
            self._start_walk()
            return
        # Re-check exactly when the quiet window would close, plus a
        # small buffer so timer jitter can't undershoot.
        self._check_timer.start(int(SIDEBAR_QUIET_MS - elapsed_ms) + 10)

    def _start_walk(self) -> None:
        """Walk one row toward the target order now, then keep ticking
        on the timer. No-op if already at target.
        """
        if self._step_timer.isActive():
            return
        self._steps_taken = 0
        # Step once now so the user sees motion immediately, not after a
        # 220 ms gap (the eye reads "trigger → motion" as causal).
        if self._step():
            self._step_timer.start()

    def _step(self) -> bool:
        """Advance one adjacent swap toward the composed target. Returns
        True if more work remains; False once converged (and stops timer).
        """
        target = self._model.target_order_ids(
            auto_arrange=self._auto_arrange_enabled(),
            group_active=self._group_enabled(),
        )
        current = [
            self._model.repo_at(i).id for i in range(self._model.rowCount())
        ]
        # If the target shifted mid-walk (a new active repo arrived,
        # activity timestamps moved), refresh the total estimate so the
        # easing curve stretches/contracts smoothly. Each step otherwise
        # decrements by 1 — O(1) instead of recomputing per tick.
        if target != self._target_cache:
            self._target_cache = target
            self._total_estimate = (
                self._steps_taken + count_bubble_swaps(current, target)
            )
        if current == target:
            self._step_timer.stop()
            return False
        for i, (cur_id, tgt_id) in enumerate(zip(current, target)):
            if cur_id == tgt_id:
                continue
            # The id that *should* sit at row i is currently lower;
            # bubble it up by one. Topmost mismatch wins so rows settle
            # from the top down — visually, the highest-priority repo
            # finishes first, then the next, etc.
            src_row = current.index(tgt_id)
            self._model.move_row_up(src_row)
            self._steps_taken += 1
            self._step_timer.setInterval(
                step_interval_ms(self._steps_taken, self._total_estimate)
            )
            return True
        self._step_timer.stop()
        return False
