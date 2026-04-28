"""Shared pytest fixtures.

`qapp` lived in four separate test files with identical setup. Pulling it here
is the canonical pytest pattern (and stops pylint from flagging the dupe).
The session scope plus the QApplication.instance() check make it safe to call
from any test that needs a Qt app instance.
"""

from __future__ import annotations

import os

import pytest

# Headless Qt — must run before the first PySide6 import in any test file.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Singleton QApplication for the whole test session.

    Returns a QApplication (not QCoreApplication) so GUI-touching tests can
    share the instance with non-GUI ones — Qt forbids switching the
    application class mid-process.
    """
    app = QCoreApplication.instance()
    if isinstance(app, QApplication):
        return app
    return QApplication([])
