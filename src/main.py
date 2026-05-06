"""ccwork GUI entry point."""

from __future__ import annotations

import logging
import os
import sys

# Force XCB before importing Qt: on Wayland, XEmbed of xterm requires both
# Qt and xterm to live on the X11 substrate (XWayland). This MUST happen
# before any Qt module is imported.
if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "xcb"

from pathlib import Path  # noqa: E402

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.core.hook_server import HookServer  # noqa: E402
from src.core.repo_store import RepoStore  # noqa: E402
from src.core.settings import load_settings, write_default_settings_file  # noqa: E402
from src.ui.main_window import MainWindow  # noqa: E402
from src.ui.qt_theme import apply_theme  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("CCWORK_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("ccwork")
    app.setApplicationDisplayName("ccwork")

    icon_path = Path(__file__).resolve().parent.parent / "logo" / "v2-icon.svg"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    store = RepoStore()
    store.load()

    # Drop a defaults file on first run so users have something to edit.
    write_default_settings_file()
    settings = load_settings()

    # Mirror the terminal palette onto the GUI chrome before any window is
    # shown, so first paint is already themed.
    apply_theme(app, settings)

    hooks = HookServer()
    hooks.start()

    win = MainWindow(store=store, hook_server=hooks, settings=settings)
    win.show()

    rc = app.exec()
    hooks.stop()
    return rc


if __name__ == "__main__":
    sys.exit(main())
