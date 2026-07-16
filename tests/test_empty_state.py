"""Tests for the empty-state / splash-dashboard shown when no terminal
is current.

What we lock down: the heading text, the version-and-tagline subhead,
the exact set of static hints shipped (so adding one is a deliberate
spec edit, not a stealthy regression), the silent-hide behavior when the
logo SVG isn't where we expect it, and the dashboard — hidden until
stats arrive, populated from a RepoStats (narrative, trend hero, facts,
release callout, bento cards, quiet strip), swapping out the onboarding
chrome once repos exist, and the rotating tip cycling through TIP_LINES.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

from src.core.repo_store import RepoStore
from src.core.settings import Settings
from src.core.repo_stats import RADAR_AXES, RepoStats, RepoWeek
from src.ui.empty_state import (
    EmptyState, HINT_LINES, RadarChart, TIP_LINES, TrendChart,
)

from tests.conftest import StubHookServer


GATHERED = 1_780_000_000    # arbitrary but fixed freshness stamp


def _stats(active: list[RepoWeek] | None = None,
           quiet: list[RepoWeek] | None = None,
           weekly: list[int] | None = None) -> RepoStats:
    s = RepoStats(active=active or [], quiet=quiet or [], gathered_ts=GATHERED)
    if weekly is not None:
        s.weekly_totals = weekly
    return s


def _active(name: str = "r", path: str = "/r", **kw) -> RepoWeek:
    kw.setdefault("commits", 5)
    kw.setdefault("insertions", 100)
    kw.setdefault("deletions", 20)
    return RepoWeek(name=name, path=path, **kw)


def test_heading_text_is_ccwork(qapp: QApplication) -> None:
    es = EmptyState(version="9.9.9")
    assert es._heading.text() == "ccwork"


def test_subhead_includes_version_string(qapp: QApplication) -> None:
    es = EmptyState(version="9.9.9")
    assert "9.9.9" in es._subhead.text()
    assert "Claude Code" in es._subhead.text()


def test_renders_without_logo(qapp: QApplication, tmp_path: Path) -> None:
    """Missing logo file → image label hidden, heading/hints still render."""
    es = EmptyState(version="0.1.0", logo_path=tmp_path / "does-not-exist.svg")
    assert es._logo.isHidden()
    assert es._heading.text() == "ccwork"
    assert len(es._hints) == len(HINT_LINES)


def test_hint_count_matches_shipped_set(qapp: QApplication) -> None:
    """Four hints shipped: Ctrl+Shift+O / right-click / Ctrl+Shift+P / F1.
    The F1 entry was added with the keyboard-cheatsheet spec (Wave 3).
    Future additions must be deliberate edits to HINT_LINES, not side
    effects."""
    es = EmptyState(version="0.1.0")
    assert len(es._hints) == 4
    assert len(HINT_LINES) == 4


def test_hints_reference_current_shortcut_namespace(qapp: QApplication) -> None:
    """Hints must use the Ctrl+Shift+N namespace shipped 2026-05-13 and
    advertise the F1 cheatsheet trigger added in Wave 3. Guards against a
    future doc-rot where the empty-state shows a shortcut that doesn't
    exist."""
    es = EmptyState(version="0.1.0")
    joined = " ".join(h.text() for h in es._hints)
    assert "Ctrl+Shift+O" in joined  # add a repo
    assert "Ctrl+Shift+P" in joined  # preferences
    assert "F1" in joined            # cheatsheet
    # Old shortcuts that were dropped must NOT appear.
    assert "Ctrl+O" not in joined.replace("Ctrl+Shift+O", "")
    assert "Ctrl+," not in joined


def test_shown_at_startup_when_no_repos(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh MainWindow with an empty repo store should display the
    EmptyState in its central stack."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = []
    store.save()
    from src.ui.main_window import MainWindow
    win = MainWindow(store=store, hook_server=StubHookServer(), settings=Settings())
    try:
        assert win._stack.currentWidget() is win._empty_placeholder
        assert isinstance(win._empty_placeholder, EmptyState)
    finally:
        win.close()


# ── dashboard ──

def test_dashboard_hidden_until_populated(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    assert es._pulse.isHidden()


def test_apply_stats_no_repos_stays_onboarding(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    es._apply_stats(_stats())  # repo_count == 0
    assert es._pulse.isHidden()
    assert not es._heading.isHidden()
    assert all(not h.isHidden() for h in es._hints)


def test_apply_stats_swaps_onboarding_for_dashboard(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    es._apply_stats(_stats(active=[_active()]))
    assert not es._pulse.isHidden()
    assert es._heading.isHidden()
    assert es._subhead.isHidden()
    assert all(h.isHidden() for h in es._hints)


def test_apply_stats_populates_dashboard(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    stats = _stats(
        active=[
            _active("busy", "/busy", commits=20, prior_commits=5,
                    new_files=3, files_changed=6, file_types=2, dirty=True),
            _active("cooling", "/cool", commits=4, prior_commits=15),
        ],
        quiet=[RepoWeek(name="asleep", path="/z", lifetime_commits=300, dirty=True)],
        weekly=[1, 2, 3, 4, 5, 6, 7, 24],
    )
    es._apply_stats(stats)
    assert es._week_total.text() == "24"
    assert es._narrative.text()                       # narrative renders
    assert "busy" in es._narrative.text()
    assert es._trend_chart._totals == [1, 2, 3, 4, 5, 6, 7, 24]
    assert "new files" in es._facts.text()
    assert len(es._cards) == 2                        # one card per active repo
    assert len(es._quiet_chips) == 1
    assert "asleep" in es._quiet_chips[0].text()
    assert "uncommitted" in es._quiet_chips[0].text()
    assert es._ship.isHidden()                        # no release this week
    assert "as of" in es._fresh_time.text()
    assert not es._pulse.isHidden()


def test_apply_stats_shows_release_callout(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    rel = _active("shipper", "/s", commits=2, release="v1.1.0",
                  release_ts=GATHERED - 3600)
    es._apply_stats(_stats(active=[rel]))
    assert not es._ship.isHidden()
    assert "shipper" in es._ship_what.text()
    assert "v1.1.0" in es._ship_what.text()
    assert es._ship_when.text() == "1h ago"


def test_apply_stats_rebuilds_cards(qapp: QApplication) -> None:
    """A second sweep must replace the prior cards/chips, not append."""
    es = EmptyState(version="0.1.0")
    es._apply_stats(_stats(active=[_active("a", "/a"), _active("b", "/b")]))
    es._apply_stats(_stats(active=[_active("c", "/c")],
                           quiet=[RepoWeek(name="q", path="/q")]))
    assert len(es._cards) == 1
    assert len(es._quiet_chips) == 1


def test_quiet_strip_hidden_when_all_active(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    es._apply_stats(_stats(active=[_active()]))
    assert es._quiet_chips == []
    assert es._quiet_title.isHidden()


# ── chart widgets ──

def test_radar_clamps_and_pads_values(qapp: QApplication) -> None:
    from PySide6.QtGui import QColor
    r = RadarChart(QColor("#268bd2"), QColor("#000"), QColor("#888"))
    r.set_values([2.0, -1.0, 0.5])
    assert r._values == (1.0, 0.0, 0.5, 0.0, 0.0, 0.0)
    assert len(r._values) == len(RADAR_AXES)


def test_trend_chart_sizes_to_bar_count(qapp: QApplication) -> None:
    from PySide6.QtGui import QColor
    t = TrendChart(QColor("#2aa198"), QColor("#000"))
    t.set_data([1] * 8)
    assert t.width() == 8 * TrendChart.BAR_W + 7 * TrendChart.GAP


def test_tip_cycles_through_lines(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    seen = {es._tip.text()}
    for _ in range(len(TIP_LINES) + 1):
        es._next_tip()
        seen.add(es._tip.text())
    assert seen == set(TIP_LINES)


def test_recovery_banner_hidden_by_default(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    assert es._recovery.isHidden()


def test_show_recovery_populates_rows(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    es.show_recovery([
        {"path": "/r/a", "name": "alpha", "id": "sid-1"},
        {"path": "/r/b", "name": "beta", "id": "sid-2"},
    ])
    assert not es._recovery.isHidden()
    assert len(es._recovery_row_widgets) == 2


def test_show_recovery_empty_hides(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    es.show_recovery([{"path": "/r/a", "name": "alpha", "id": "sid-1"}])
    es.show_recovery([])
    assert es._recovery.isHidden()
    assert es._recovery_row_widgets == []


def test_dismiss_emits_and_hides(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    es.show_recovery([{"path": "/r/a", "name": "alpha", "id": "sid-1"}])
    fired = []
    es.recovery_dismissed.connect(lambda: fired.append(True))
    es._on_dismiss()
    assert fired == [True]
    assert es._recovery.isHidden()


def test_copy_puts_text_on_clipboard_and_signals(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    msgs = []
    es.status_message.connect(msgs.append)
    es._copy("claude --resume sid-1", "Resume command copied")
    assert QApplication.clipboard().text() == "claude --resume sid-1"
    assert msgs == ["Resume command copied"]


def _row_button(es, row_idx: int, label: str):
    from PySide6.QtWidgets import QPushButton
    btns = es._recovery_row_widgets[row_idx].findChildren(QPushButton)
    return next(b for b in btns if b.text() == label)


def test_rows_have_labeled_copy_and_launch_buttons(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    es.show_recovery([{"path": "/r/a", "name": "alpha", "id": "sid-1"}])
    from PySide6.QtWidgets import QPushButton
    labels = {b.text() for b in es._recovery_row_widgets[0].findChildren(QPushButton)}
    assert labels == {"Copy", "Launch"}


def test_copy_button_copies_session_id(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    es.show_recovery([{"path": "/r/a", "name": "alpha", "id": "sid-xyz"}])
    _row_button(es, 0, "Copy").click()
    assert QApplication.clipboard().text() == "sid-xyz"


def test_launch_button_emits_resume_requested(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    got = []
    es.resume_requested.connect(lambda p, s: got.append((p, s)))
    es.show_recovery([{"path": "/r/a", "name": "alpha", "id": "sid-1"}])
    _row_button(es, 0, "Launch").click()
    assert got == [("/r/a", "sid-1")]
