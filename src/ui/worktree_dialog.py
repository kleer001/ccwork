"""The worktree dialogs of the row menu: "Make worktree…"
(docs/specs/worktree.md 5.2) and "Remove from sidebar" on a worktree row (7)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from src.core.worktree import (
    GitError, WorktreePlan, has_submodules, ignored_entries, worktree_plan, worktree_source,
)
from src.ui.badge_theme import STATUS_ATTENTION, STATUS_COLORS

REASON_STYLE = f"color: {STATUS_COLORS[STATUS_ATTENTION].name()};"

# Names the remove dialog lists before "and N more".
IGNORED_LIST_MAX = 10


class WorktreeDialog(QDialog):
    """Ask for the branch name of a new worktree and show what OK makes.
    OK stays off, with the reason, while the plan cannot run
    (docs/specs/worktree.md 5.2)."""

    def __init__(self, source_path: str, base: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Make worktree")
        self._source = worktree_source(source_path)
        self._base = base
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
        return worktree_plan(self._source, self._name.text().strip(), self._base)

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


class WorktreeRemoveDialog(QDialog):
    """Remove a worktree row, with an opt-in delete of the folder and its
    branch. The box is off by default. It is off and disabled, with each
    reason, when `blocked` names one or the worktree has submodules."""

    def __init__(self, folder: str, blocked: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Remove from sidebar")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Remove the row for {folder}?", self))
        self._box = QCheckBox("Also delete the worktree folder and its branch", self)
        layout.addWidget(self._box)
        reasons = [blocked] if blocked else []
        if has_submodules(folder):
            reasons.append("The worktree has submodules. Git does not delete it.")
        reason = " ".join(reasons)
        if reason:
            self._box.setEnabled(False)
            note = QLabel(reason, self)
            note.setStyleSheet(REASON_STYLE)
            layout.addWidget(note)
        entries = ignored_entries(folder)
        if entries:
            layout.addWidget(QLabel("These ignored files and folders are deleted too:", self))
            names = entries[:IGNORED_LIST_MAX]
            rest = len(entries) - len(names)
            layout.addWidget(QLabel("\n".join(names + ([f"and {rest} more"] if rest else [])), self))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def delete_checked(self) -> bool:
        return self._box.isChecked()
