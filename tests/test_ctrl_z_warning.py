"""Smoke tests for the Ctrl+Z warning dialog.

We can't fire a real modal exec in offscreen tests, so the strategy is to
override ``QMessageBox.exec`` to programmatically activate one of the
known buttons (or none) before exec returns. ``clickedButton`` and the
checkbox state then drive the public return value the way they would for
a real user click.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from src.ui.ctrl_z_warning import show_ctrl_z_warning


@pytest.fixture
def click_button(monkeypatch):
    """Patch QMessageBox.exec to "click" a button matching `text` (or none)."""
    def _setup(*, text: str | None, uncheck: bool = False):
        def fake_exec(self: QMessageBox) -> int:
            if uncheck and self.checkBox() is not None:
                self.checkBox().setChecked(False)
            target = next(
                (b for b in self.buttons() if text is not None and b.text() == text),
                None,
            )
            if target is not None:
                target.click()
            return 0
        monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return _setup


def test_confirm_keeps_warning_by_default(qapp, click_button) -> None:
    click_button(text="Send Ctrl+Z")
    result = show_ctrl_z_warning(None)
    assert result.send_signal is True
    assert result.keep_warning is True


def test_cancel_does_not_send(qapp, click_button) -> None:
    click_button(text="Cancel")
    result = show_ctrl_z_warning(None)
    assert result.send_signal is False
    # Cancel must never silence the warning — only an explicit uncheck
    # while confirming can.
    assert result.keep_warning is True


def test_confirm_with_uncheck_disables_warning(qapp, click_button) -> None:
    click_button(text="Send Ctrl+Z", uncheck=True)
    result = show_ctrl_z_warning(None)
    assert result.send_signal is True
    assert result.keep_warning is False


def test_cancel_with_uncheck_still_keeps_warning(qapp, click_button) -> None:
    """Defensive: even if a user unchecks the box and then clicks Cancel,
    leave the warning enabled. Disabling a safety net should require an
    affirmative action."""
    click_button(text="Cancel", uncheck=True)
    result = show_ctrl_z_warning(None)
    assert result.send_signal is False
    assert result.keep_warning is True
