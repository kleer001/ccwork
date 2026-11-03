"""The "Make worktree…" dialog of the row menu (docs/specs/worktree.md 5.2)."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from src.core.worktree import GitError, WorktreePlan, worktree_plan, worktree_source
from src.ui.badge_theme import STATUS_ATTENTION, STATUS_COLORS

REASON_STYLE = f"color: {STATUS_COLORS[STATUS_ATTENTION].name()};"


class WorktreeDialog(QDialog):
    """Ask for the branch name of a new worktree and show what OK makes.
    OK stays off, with the reason, while the plan cannot run
    (docs/specs/worktree.md 5.2)."""

    def __init__(self, source_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Make worktree")
        self._source = worktree_source(source_path)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("A worktree is a second folder on a new branch, in the same repository."))
        self._name = QLineEdit(self)
        self._name.setPlaceholderText("Branch name, for example fix/login")
        layout.addWidget(self._name)
        self._folder = QLabel(self)
        self._branch = QLabel(self)
        src = self._source
        start = QLabel(f"Start: from {src.base or 'detached HEAD'} at {src.commit}", self)
        layout.addWidget(self._folder)
        layout.addWidget(self._branch)
        layout.addWidget(start)
        if src.dirty:
            dirty = QLabel(f"Uncommitted changes stay in {src.path}. "
                           "The new worktree does not get them.", self)
            dirty.setWordWrap(True)
            layout.addWidget(dirty)
        self._problem = QLabel(self)
        self._problem.setStyleSheet(REASON_STYLE)
        layout.addWidget(self._problem)
        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._name.textChanged.connect(self._update)
        self._update()

    def plan(self) -> WorktreePlan:
        return worktree_plan(self._source, self._name.text().strip())

    def _update(self) -> None:
        try:
            plan = self.plan()
        except GitError as e:
            self._problem.setText(str(e))
            self._buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        self._folder.setText(f"Folder: {plan.folder}" if plan.name else "Folder:")
        self._branch.setText(f"Branch: {plan.name}")
        self._problem.setText(plan.problem)
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(not plan.problem)

