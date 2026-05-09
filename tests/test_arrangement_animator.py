"""Pure-function tests for the arrangement animator helpers.

These don't need a QApplication — they exercise the math behind the
bubble-walk animation. The integration paths (timers, model
interaction) are exercised by the existing
test_repo_sidebar_grouping.py.
"""

from __future__ import annotations

import pytest

from src.ui.arrangement_animator import (
    ARRANGE_STEP_MAX_MS,
    ARRANGE_STEP_MIN_MS,
    count_bubble_swaps,
    step_interval_ms,
)

# ── count_bubble_swaps: equals the inversion count between current and target ──


def test_count_swaps_zero_when_already_sorted() -> None:
    assert count_bubble_swaps(["a", "b", "c"], ["a", "b", "c"]) == 0


def test_count_swaps_one_for_a_single_adjacent_swap() -> None:
    assert count_bubble_swaps(["b", "a", "c"], ["a", "b", "c"]) == 1


def test_count_swaps_two_for_a_two_step_bubble() -> None:
    # C is two rows from where it should be → 2 move_row_up calls.
    assert count_bubble_swaps(["c", "a", "b", "d"], ["a", "b", "c", "d"]) == 2


def test_count_swaps_full_reversal() -> None:
    # n=4 reverse: 6 inversions = n(n-1)/2.
    assert count_bubble_swaps(["d", "c", "b", "a"], ["a", "b", "c", "d"]) == 6


def test_count_swaps_handles_unknown_ids_gracefully() -> None:
    # An id not in target gets target_pos = its current row, so it never
    # contributes an inversion. Useful when the target is computed from
    # a different snapshot of repos than `current` reflects.
    assert count_bubble_swaps(["a", "ghost", "b"], ["a", "b"]) == 0


# ── step_interval_ms: sine ease-in-out endpoints + midpoint ──


def test_interval_at_low_total_returns_max() -> None:
    # 1- or 2-swap walks: too few for a meaningful curve, slow & deliberate.
    assert step_interval_ms(steps_taken=1, total=1) == ARRANGE_STEP_MAX_MS
    assert step_interval_ms(steps_taken=1, total=2) == ARRANGE_STEP_MAX_MS


def test_interval_first_gap_is_max() -> None:
    # At the first gap (steps_taken=1, x=0), sin(0)=0 → MAX.
    assert step_interval_ms(steps_taken=1, total=10) == ARRANGE_STEP_MAX_MS


def test_interval_last_gap_is_max() -> None:
    # At the last gap (steps_taken=total-1, x=1), sin(π)≈0 → MAX.
    # `round` (not int) absorbs the float drift at sin(π).
    assert step_interval_ms(steps_taken=9, total=10) == ARRANGE_STEP_MAX_MS


def test_interval_middle_is_min() -> None:
    # At x=0.5 (steps_taken-1 == (total-2)/2), sin(π/2)=1 → MIN.
    assert step_interval_ms(steps_taken=5, total=10) == ARRANGE_STEP_MIN_MS


def test_interval_clamps_overshoot() -> None:
    # _step occasionally overruns by 1 right before the timer stops; we
    # clamp x≤1.0 so the result stays valid (not negative or huge).
    val = step_interval_ms(steps_taken=11, total=10)
    assert ARRANGE_STEP_MIN_MS <= val <= ARRANGE_STEP_MAX_MS


@pytest.mark.parametrize("total", [3, 5, 10, 50])
def test_interval_endpoints_always_at_max(total: int) -> None:
    assert step_interval_ms(steps_taken=1, total=total) == ARRANGE_STEP_MAX_MS
    assert step_interval_ms(steps_taken=total - 1, total=total) == ARRANGE_STEP_MAX_MS
