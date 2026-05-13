"""Right-click context menu for an embedded xterm.

`TerminalHost` emits `context_menu_requested(QPoint)` on plain right-click;
MainWindow turns that into a `build_terminal_menu(...)` call and execs the
result at the global cursor position. This module owns the action labels,
tooltips, separator placement, and the disabled "Copy selection" hint —
not the callback wiring (callers pass in `on_paste` / `on_reload` /
`on_preferences`).
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QWidget


def build_terminal_menu(
    parent: QWidget,
    *,
    on_paste: Callable[[], None],
    on_reload: Callable[[], None],
    on_preferences: Callable[[], None],
) -> QMenu:
    """Construct (but don't show) the terminal right-click menu.

    The caller is responsible for `menu.exec(global_pos)`. `parent` becomes
    the menu's Qt parent for lifetime management; the menu does not
    reparent on `exec`.
    """
    menu = QMenu(parent)

    paste = QAction("Paste", menu)
    paste.setToolTip("Send clipboard text to the terminal (Ctrl+Shift+V)")
    paste.triggered.connect(lambda _=False: on_paste())
    menu.addAction(paste)

    # xterm owns the X selection — only xterm can write a selection to
    # the clipboard. Hint at the keybind rather than offering a Copy
    # action we can't actually execute from Qt.
    copy_hint = QAction("Copy selection   Ctrl+Shift+C", menu)
    copy_hint.setEnabled(False)
    menu.addAction(copy_hint)

    menu.addSeparator()

    reload_act = QAction("Reload terminal", menu)
    reload_act.triggered.connect(lambda _=False: on_reload())
    menu.addAction(reload_act)

    prefs = QAction("Preferences…", menu)
    prefs.triggered.connect(lambda _=False: on_preferences())
    menu.addAction(prefs)

    return menu
