"""Large title strip showing the currently-focused repo name."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QSizePolicy


class TitleLabel(QLabel):
    """Top-left header bound to the active repo."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        f = QFont()
        f.setPointSize(16)
        f.setBold(True)
        self.setFont(f)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setContentsMargins(10, 4, 10, 4)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.set_repo(None)

    def set_repo(self, name: str | None) -> None:
        self.setText(name or "ccwork")
