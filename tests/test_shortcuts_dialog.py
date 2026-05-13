"""Tests for the keyboard-shortcuts cheatsheet dialog.

The SHORTCUTS table is the user-visible source of truth for the
cheatsheet. Tests lock down which groups exist and which specific
keystrokes are listed, catching the most common drift (a binding gets
added to `_install_global_keys` but nobody updates SHORTCUTS, or
someone deletes the table during a refactor).

The F1 / Shift+? trigger registration in `_install_global_keys` is not
unit-tested — it needs a real xcb display to verify the XGrabKey grab.
That's covered by the manual SMOKE-TEST checklist instead.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ui.shortcuts_dialog import SHORTCUTS, ShortcutsDialog


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_shortcuts_table_has_expected_groups() -> None:
    groups = [g for g, _ in SHORTCUTS]
    assert "Window" in groups
    assert "Sidebar" in groups
    assert "Terminal" in groups


def test_shortcuts_table_covers_known_bindings() -> None:
    """Flatten the table and confirm each shipped binding has a row.

    The keystrokes here mirror the SHORTCUTS table entries, not the raw
    bindings — display formatting like `Ctrl+Shift+1 … Ctrl+Shift+9` for
    the row-jump range is what users see in the cheatsheet, and that's
    what we lock in.
    """
    flat = [keystroke for _, rows in SHORTCUTS for _, keystroke in rows]
    must_appear = [
        "Ctrl+Shift+P",                # Preferences
        "Ctrl+Shift+O",                # Add repo
        "Ctrl+Shift+Q",                # Quit
        "F1",                          # Cheatsheet trigger (in "F1  /  ?")
        "Ctrl+Tab",                    # Next repo
        "Ctrl+Shift+Tab",              # Previous repo
        "Ctrl+Shift+1",                # Row-jump range start
        "Ctrl+Shift+9",                # Row-jump range end
        "Ctrl+0",                      # Reset zoom
        "Ctrl+scroll",                 # Mouse-wheel zoom
        "Ctrl+Shift+C",                # Xterm-owned copy
        "Ctrl+Shift+V",                # Xterm-owned paste
        "Right-click",                 # Context menu
    ]
    for token in must_appear:
        assert any(token in row for row in flat), (
            f"SHORTCUTS missing a row containing {token!r}; "
            f"current rows = {flat}"
        )


def test_dialog_instantiates_and_lists_entries(qapp: QApplication) -> None:
    dlg = ShortcutsDialog()
    try:
        assert dlg.windowTitle() == "Keyboard shortcuts"
        # At minimum the three established groups' worth of rows.
        total_rows = sum(len(rows) for _, rows in SHORTCUTS)
        assert total_rows >= 10
    finally:
        dlg.deleteLater()


def test_shortcuts_namespace_is_post_rework(qapp: QApplication) -> None:
    """Regression guard: SHORTCUTS must not reference the pre-2026-05-13
    bindings (Ctrl+,, Ctrl+O without Shift, Ctrl+Q without Shift, Alt+N).
    Those were removed when the namespace migrated to Ctrl+Shift+*."""
    flat = [row for _, rows in SHORTCUTS for row in rows]
    flat_keystrokes = [k for _, k in flat]
    joined = " | ".join(flat_keystrokes)
    # Bare Ctrl+, was Preferences pre-rework; now it's nothing.
    assert "Ctrl+," not in joined
    # Bare Ctrl+O / Ctrl+Q without Shift used to mean add-repo / quit but
    # collide with readline / tty driver — we explicitly moved them.
    # (Substring check is fine: there is no other "Ctrl+O" / "Ctrl+Q"
    # we'd want to surface.)
    bare_co = [k for k in flat_keystrokes if "Ctrl+O" in k and "Shift" not in k]
    bare_cq = [k for k in flat_keystrokes if "Ctrl+Q" in k and "Shift" not in k]
    assert bare_co == [], f"unexpected bare Ctrl+O rows: {bare_co}"
    assert bare_cq == [], f"unexpected bare Ctrl+Q rows: {bare_cq}"
    # Alt+N row-jump was abandoned because xterm metaSendsEscape consumes
    # it; the namespace is Ctrl+Shift+N now.
    alt_n = [k for k in flat_keystrokes if k.startswith("Alt+") and any(d in k for d in "0123456789")]
    assert alt_n == [], f"unexpected Alt+digit rows: {alt_n}"


def test_question_mark_is_not_a_trigger(qapp: QApplication) -> None:
    """Regression guard: ? was briefly a secondary cheatsheet trigger
    but conflicted with typing `?` in the embedded xterm / shells / code
    editors. Dropped 2026-05-13. SHORTCUTS must not list it."""
    flat = [row for _, rows in SHORTCUTS for row in rows]
    f1_rows = [k for _, k in flat if "F1" in k]
    assert f1_rows == ["F1"], f"F1 row should be just 'F1', got: {f1_rows}"
