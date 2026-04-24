"""Top-right panel listing recent Stop/Notification events."""

from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QSizePolicy


MAX_ROWS = 25

# Qt.UserRole slot on each list item, storing the source repo's cwd so a
# click can jump the main window to that repo.
_ROLE_CWD = Qt.UserRole + 1


@dataclass
class AlertEntry:
    event: str           # "Stop" | "Notification" | "RepoAdded" | ...
    repo_name: str       # basename of cwd, or "?" if unknown
    message: str         # payload-derived short text
    ts: float            # epoch seconds
    cwd: str | None = None  # source repo path; None for alerts with no repo


def _format_row(a: AlertEntry) -> str:
    hhmm = time.strftime("%H:%M", time.localtime(a.ts))
    sigil = {"Stop": "✓", "Notification": "●", "RepoAdded": "+"}.get(a.event, "·")
    return f"{hhmm}  {sigil}  [{a.repo_name}]  {a.message}"


class AlertsPanel(QListWidget):
    """Most-recent-first alert list. Bounded to `MAX_ROWS` entries.

    Clicking an entry with a cwd emits `repo_requested(str)` so the main
    window can jump to that repo.
    """

    repo_requested = Signal(str)  # emits cwd

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        # We want clicks to register but not draw the usual selection
        # highlight — the alert is a jump button, not a persistent choice.
        self.setSelectionMode(QListWidget.NoSelection)
        self.setWordWrap(False)
        self.setMaximumWidth(500)
        self.setMinimumWidth(250)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.itemClicked.connect(self._on_clicked)

    def add_alert(self, entry: AlertEntry) -> None:
        item = QListWidgetItem(_format_row(entry))
        item.setToolTip(
            f"{entry.message}\n\nClick to jump to repo." if entry.cwd else entry.message
        )
        if entry.cwd:
            item.setData(_ROLE_CWD, entry.cwd)
        self.insertItem(0, item)
        while self.count() > MAX_ROWS:
            self.takeItem(self.count() - 1)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        cwd = item.data(_ROLE_CWD)
        if isinstance(cwd, str) and cwd:
            self.repo_requested.emit(cwd)
