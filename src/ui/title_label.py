"""Centered top-bar label showing the active `repo · branch`."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class TitleLabel(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        self.setFont(f)
        self.setAlignment(Qt.AlignCenter)
        self.setContentsMargins(10, 2, 10, 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.set_repo(None, None)

    def set_repo(self, name: str | None, branch: str | None = None) -> None:
        if not name:
            self.setText("ccwork")
            return
        self.setText(f"{name}  ·  {branch}" if branch else name)
