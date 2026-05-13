"""Modal dialog listing every keyboard shortcut, grouped by context.

Triggered by F1 (and `?`, which is Shift+/ on US layouts — silently
fails to bind on layouts where `?` requires AltGr; F1 is the
documented primary). Wired in
``MainWindow._install_global_keys`` alongside the rest of the
root-window XGrabKey table, and dispatched via the
``QAbstractNativeEventFilter`` — see ``src/core/key_grab.py``.

The shortcut table is **manual**: a derived list would auto-sync with
the bindings table in ``_install_global_keys`` but couldn't cover the
xterm-owned ``Ctrl+Shift+C`` / ``Ctrl+Shift+V`` (those have no Qt
representation — they're baked into the ``-xrm`` translations in
``XtermSettings.to_xterm_args``). Hand-writing half and deriving the
other half is worse than hand-writing all of it. The test suite's
``test_shortcuts_table_covers_known_bindings`` catches the most
common drift.

# When adding a shortcut, update SHORTCUTS below AND the relevant
# binding site:
#   • Window / Sidebar / zoom keys → ``MainWindow._install_global_keys``
#     bindings list (``src/ui/main_window.py``).
#   • Ctrl+wheel and right-click → ``TerminalHost._install_button_grabs``
#     (``src/ui/terminal_host.py``).
#   • Xterm-owned (``Ctrl+Shift+C`` / ``Ctrl+Shift+V``) → the ``-xrm``
#     translations in ``XtermSettings.to_xterm_args``
#     (``src/core/settings.py``).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


# Source of truth for the cheatsheet. Each entry is a (group, [(action,
# keystroke), ...]) tuple. Keystrokes are display strings — em-spaced
# alternatives, parenthetical annotations are fine; the renderer takes
# them verbatim.
SHORTCUTS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Window", [
        ("Preferences",         "Ctrl+Shift+P"),
        ("Add repo",            "Ctrl+Shift+O"),
        ("Quit",                "Ctrl+Shift+Q"),
        ("Keyboard shortcuts",  "F1  /  ?"),
    ]),
    ("Sidebar", [
        ("Jump to repo 1..9",   "Ctrl+Shift+1 … Ctrl+Shift+9"),
        ("Next repo",           "Ctrl+Tab"),
        ("Previous repo",       "Ctrl+Shift+Tab"),
    ]),
    ("Terminal", [
        ("Zoom in",             "Ctrl+=  /  Ctrl++"),
        ("Zoom out",            "Ctrl+-"),
        ("Reset zoom",          "Ctrl+0"),
        ("Zoom (mouse)",        "Ctrl+scroll"),
        ("Copy selection",      "Ctrl+Shift+C  (xterm)"),
        ("Paste",               "Ctrl+Shift+V"),
        ("Context menu",        "Right-click"),
    ]),
]


class ShortcutsDialog(QDialog):
    """Read-only cheatsheet. Scrollable so it stays usable at small heights."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        self.setModal(True)
        self.resize(480, 520)

        # Monospace for the keystroke column so multi-key sequences align
        # visually. systemFont(FixedFont) yields the platform's default
        # monospace, which matches the user's terminal font reasonably
        # closely on most setups.
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)

        # Build group boxes inside a scroll area so tall content scrolls
        # rather than forcing the dialog past the screen height.
        groups_container = QWidget(self)
        groups_layout = QVBoxLayout(groups_container)
        groups_layout.setContentsMargins(0, 0, 0, 0)
        groups_layout.setSpacing(8)
        for group_name, rows in SHORTCUTS:
            if not rows:
                # Skip empty groups so we don't render a blank box.
                continue
            box = QGroupBox(group_name, groups_container)
            form = QFormLayout(box)
            form.setLabelAlignment(Qt.AlignLeft)
            for action, keystroke in rows:
                left = QLabel(action, box)
                right = QLabel(keystroke, box)
                right.setFont(mono)
                right.setTextInteractionFlags(Qt.TextSelectableByMouse)
                form.addRow(left, right)
            groups_layout.addWidget(box)
        groups_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(groups_container)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addWidget(buttons, 0)
