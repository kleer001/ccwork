"""Confirm-before-sending dialog for the intercepted Ctrl+Z shortcut.

In a shell Ctrl+Z sends SIGTSTP to the foreground process (typically
Claude), which suspends it and drops the user back at a bash prompt —
the stopped session looks gone until `fg`. MainWindow installs a passive
XGrabKey for Ctrl+Z while ``UISettings.warn_on_ctrl_z`` is True; when
the key fires it routes here, and the result decides whether to inject
the byte into the PTY and whether to leave the warning enabled.

The dialog deliberately uses ``QMessageBox.setCheckBox`` so the
"silence" affordance lives next to the buttons (one click to dismiss
forever) rather than as a follow-up prompt.
"""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtWidgets import QCheckBox, QMessageBox, QWidget


class CtrlZWarningResult(NamedTuple):
    send_signal: bool   # user confirmed sending Ctrl+Z (SIGTSTP) through
    keep_warning: bool  # leave the warning enabled for next time


def show_ctrl_z_warning(parent: QWidget | None) -> CtrlZWarningResult:
    """Modal warning shown when Ctrl+Z is intercepted in the terminal.

    Returns the user's choices. Cancel returns ``send_signal=False`` and
    leaves the warning enabled — unchecking the box is the only way to
    silence it, so an accidental dismissal can't disable the safety net.
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Send Ctrl+Z?")
    box.setText("Ctrl+Z will suspend the running process (probably Claude).")
    box.setInformativeText(
        "The session stops and drops to a bash prompt. Type `fg` to resume it."
    )
    send_btn = box.addButton("Send Ctrl+Z", QMessageBox.AcceptRole)
    cancel_btn = box.addButton(QMessageBox.Cancel)
    box.setDefaultButton(cancel_btn)
    checkbox = QCheckBox("Show this warning next time")
    checkbox.setChecked(True)
    box.setCheckBox(checkbox)
    box.exec()
    send = box.clickedButton() is send_btn
    keep = checkbox.isChecked() if send else True
    return CtrlZWarningResult(send_signal=send, keep_warning=keep)
