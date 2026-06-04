"""Tests for the empty-state / splash placeholder shown when no terminal
is current.

What we lock down: the heading text, the version-and-tagline subhead,
the exact set of static hints shipped (so adding one is a deliberate
spec edit, not a stealthy regression), the silent-hide behavior when the
logo SVG isn't where we expect it, and the live git-pulse block —
hidden until stats arrive, populated from a RepoStats, and the rotating
tip cycling through TIP_LINES.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

from src.core.repo_store import RepoStore
from src.core.settings import Settings
from src.core.repo_stats import RecentActivity, RepoStats
from src.ui.empty_state import EmptyState, HINT_LINES, TIP_LINES

from tests.conftest import StubHookServer


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


# ── git-pulse bento ──

def test_pulse_hidden_until_populated(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    assert es._pulse.isHidden()


def test_apply_stats_populates_tiles(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    stats = RepoStats(
        repo_count=3,
        dirty_count=2,
        dirty_names=["ccwork", "image_gen"],
        commits_this_week=5,
        daily_counts=[0, 1, 0, 2, 0, 1, 1],
        today_index=3,
        recent=RecentActivity(name="ccwork", subject="fix thing", ts=1_700_000_000),
    )
    es._apply_stats(stats)
    assert es._week_total.text() == "5"
    assert es._repos_num.text() == "3"
    assert es._dirty_num.text() == "2"
    # uncommitted repos are listed by name
    listed = [lbl.text() for lbl in es._dirty_name_labels]
    assert listed == ["• ccwork", "• image_gen"]
    assert es._chart._counts == [0, 1, 0, 2, 0, 1, 1]
    assert es._chart._today_idx == 3
    assert "fix thing" in es._recent.text()
    assert not es._pulse.isHidden()


def test_apply_stats_rebuilds_dirty_list(qapp: QApplication) -> None:
    """A second sweep must replace the prior names, not append."""
    es = EmptyState(version="0.1.0")
    es._apply_stats(RepoStats(repo_count=2, dirty_count=1, dirty_names=["a"]))
    es._apply_stats(RepoStats(repo_count=2, dirty_count=2, dirty_names=["b", "c"]))
    assert [lbl.text() for lbl in es._dirty_name_labels] == ["• b", "• c"]


def test_apply_stats_no_repos_stays_hidden(qapp: QApplication) -> None:
    es = EmptyState(version="0.1.0")
    es._apply_stats(RepoStats())  # repo_count == 0
    assert es._pulse.isHidden()


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
