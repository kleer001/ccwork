"""ccwork GUI entry point."""

from __future__ import annotations

import logging
import logging.handlers
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


def _setup_hook_event_log() -> None:
    """Always-on rotating DEBUG log for hook traffic only.

    Writes every received hook event to ~/.cache/ccwork/hooks.log so post-hoc
    diagnosis ("why did the green dot light up while Claude was still
    working?") doesn't require re-launching with CCWORK_LOG=DEBUG. Bounded
    size (5 × 256 KiB), only the hook_server logger feeds it, so the rest
    of the app's logging behavior is unchanged.
    """
    log_dir = Path.home() / ".cache" / "ccwork"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "hooks.log",
        maxBytes=256 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    hook_logger = logging.getLogger("src.core.hook_server")
    hook_logger.setLevel(logging.DEBUG)
    hook_logger.addHandler(handler)
    # Don't pollute stderr with DEBUG payload dumps — the file is the only
    # consumer of the verbose stream. WARNINGs (malformed lines) are still
    # captured in the file and are easier to grep there anyway.
    hook_logger.propagate = False


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("CCWORK_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _setup_hook_event_log()
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("ccwork")
    app.setApplicationDisplayName("ccwork")

    icon_path = Path(__file__).resolve().parent.parent / "assets" / "v2-icon.svg"
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
