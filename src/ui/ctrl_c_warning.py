"""Confirm-before-sending dialog for the intercepted Ctrl+C shortcut.

Newcomers from non-terminal apps muscle-memory Ctrl+C as "copy". In a
shell it sends SIGINT to the foreground process (typically Claude),
which can clobber an in-flight session. MainWindow installs a passive
XGrabKey for Ctrl+C while ``UISettings.warn_on_ctrl_c`` is True; when
the key fires it routes here, and the result decides whether to inject
the byte into the PTY and whether to leave the warning enabled.

The dialog deliberately uses ``QMessageBox.setCheckBox`` so the
"silence" affordance lives next to the buttons (one click to dismiss
forever) rather than as a follow-up prompt.
"""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtWidgets import QCheckBox, QMessageBox, QWidget


class CtrlCWarningResult(NamedTuple):
    send_signal: bool   # user confirmed sending Ctrl+C (SIGINT) through
    keep_warning: bool  # leave the warning enabled for next time


def show_ctrl_c_warning(parent: QWidget | None) -> CtrlCWarningResult:
    """Modal warning shown when Ctrl+C is intercepted in the terminal.

    Returns the user's choices. Cancel returns ``send_signal=False`` and
    leaves the warning enabled — unchecking the box is the only way to
    silence it, so an accidental dismissal can't disable the safety net.
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Send Ctrl+C?")
    box.setText("Ctrl+C will interrupt the running process (probably Claude).")
    box.setInformativeText(
        "To copy text from the terminal, use Ctrl+Shift+C instead."
    )
    send_btn = box.addButton("Send Ctrl+C", QMessageBox.AcceptRole)
    cancel_btn = box.addButton(QMessageBox.Cancel)
    box.setDefaultButton(cancel_btn)
    checkbox = QCheckBox("Show this warning next time")
    checkbox.setChecked(True)
    box.setCheckBox(checkbox)
    box.exec()
    send = box.clickedButton() is send_btn
    keep = checkbox.isChecked() if send else True
    return CtrlCWarningResult(send_signal=send, keep_warning=keep)
