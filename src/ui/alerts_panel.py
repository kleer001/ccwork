"""Top-right panel listing recent Stop/Notification events."""

from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QSizePolicy


MAX_ROWS = 25


@dataclass
class AlertEntry:
    event: str           # "Stop" | "Notification" | "RepoAdded" | ...
    repo_name: str       # basename of cwd, or "?" if unknown
    message: str         # payload-derived short text
    ts: float            # epoch seconds


def _format_row(a: AlertEntry) -> str:
    hhmm = time.strftime("%H:%M", time.localtime(a.ts))
    sigil = {"Stop": "✓", "Notification": "●", "RepoAdded": "+"}.get(a.event, "·")
    return f"{hhmm}  {sigil}  [{a.repo_name}]  {a.message}"


class AlertsPanel(QListWidget):
    """Most-recent-first alert list. Bounded to `MAX_ROWS` entries."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSelectionMode(QListWidget.NoSelection)
        self.setWordWrap(False)
        self.setMaximumWidth(500)
        self.setMinimumWidth(250)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    def add_alert(self, entry: AlertEntry) -> None:
        item = QListWidgetItem(_format_row(entry))
        item.setToolTip(entry.message)
        self.insertItem(0, item)
        while self.count() > MAX_ROWS:
            self.takeItem(self.count() - 1)
