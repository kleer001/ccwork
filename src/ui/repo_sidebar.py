"""Left-hand repo list with per-row name / branch / unread badge."""

from __future__ import annotations

import os

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from src.core import repo_store
from src.core.repo_store import Repo, RepoStore


# Custom roles — keep the model backed by a single Repo per row plus branch
# + status. The view's delegate reads these directly. STATUS is one of:
# "" (no badge), "done" (Claude finished a turn), "attention" (Claude needs
# input). Color-coded by the delegate.
ROLE_REPO   = Qt.UserRole + 1
ROLE_BRANCH = Qt.UserRole + 2
ROLE_STATUS = Qt.UserRole + 3

STATUS_DONE      = "done"
STATUS_ATTENTION = "attention"


class RepoListModel(QAbstractListModel):
    """Model backed by a RepoStore plus per-repo branch + unread counters."""

    def __init__(self, store: RepoStore, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._branches: dict[str, str | None] = {}
        self._status: dict[str, str] = {}

    # ── Qt model API ──

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._store.repos)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._store.repos):
            return None
        repo = self._store.repos[index.row()]
        if role == Qt.DisplayRole:
            return repo.name
        if role == ROLE_REPO:
            return repo
        if role == ROLE_BRANCH:
            return self._branches.get(repo.path)
        if role == ROLE_STATUS:
            return self._status.get(repo.path, "")
        if role == Qt.ToolTipRole:
            return repo.path
        return None

    # ── helpers ──

    def repo_at(self, row: int) -> Repo | None:
        if 0 <= row < len(self._store.repos):
            return self._store.repos[row]
        return None

    def index_of(self, path: str) -> int:
        real = os.path.realpath(path)
        for i, r in enumerate(self._store.repos):
            if os.path.realpath(r.path) == real:
                return i
        return -1

    def refresh_branches(self) -> None:
        """Recompute branch subtitle for every repo. Call on focus/refresh."""
        changed = False
        for r in self._store.repos:
            new = repo_store.current_branch(r.path)
            if self._branches.get(r.path) != new:
                self._branches[r.path] = new
                changed = True
        if changed and self._store.repos:
            top = self.index(0)
            bot = self.index(len(self._store.repos) - 1)
            self.dataChanged.emit(top, bot, [ROLE_BRANCH])

    def set_status(self, path: str, status: str) -> None:
        """Set the per-repo status badge ("done", "attention", or "" to clear)."""
        if status:
            self._status[path] = status
        else:
            self._status.pop(path, None)
        row = self.index_of(path)
        if row >= 0:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [ROLE_STATUS])

    def clear_status(self, path: str) -> None:
        self.set_status(path, "")

    # ── add/remove piped from the store ──

    def reload(self) -> None:
        self.beginResetModel()
        self._store.load()
        self.endResetModel()

    def add_repo(self, path: str) -> bool:
        added = self._store.add(path)
        if not added:
            return False
        row = len(self._store.repos) - 1
        self.beginInsertRows(QModelIndex(), row, row)
        self.endInsertRows()
        self._store.save()
        # Populate branch for the newly added row so the subtitle isn't
        # blank until the next focus-triggered refresh. Cheap: one git call.
        repo = self._store.repos[row]
        self._branches[repo.path] = repo_store.current_branch(repo.path)
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [ROLE_BRANCH])
        return True

    def remove_repo_at(self, row: int) -> bool:
        if not (0 <= row < len(self._store.repos)):
            return False
        path = self._store.repos[row].path
        self.beginRemoveRows(QModelIndex(), row, row)
        self._store.remove(path)
        self.endRemoveRows()
        self._branches.pop(path, None)
        self._status.pop(path, None)
        self._store.save()
        return True


class RepoDelegate(QStyledItemDelegate):
    """Two-line row: name (bold) + branch (subtitle), unread badge right-aligned."""

    ROW_HEIGHT = 52
    PADDING_X = 10
    # Solarized-ish: red = needs attention (urgent), green = done (calmer).
    STATUS_COLORS = {
        STATUS_ATTENTION: QColor(220, 50, 47),   # solarized red
        STATUS_DONE:      QColor(133, 153, 0),   # solarized green
    }

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    # Left-edge stripe width for the active/selected row. Thin enough to
    # not crowd the text, thick enough to read at a glance.
    ACTIVE_STRIPE_W = 3

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()

        # Background: honor selection state. The selected row IS the active
        # repo because selecting switches the stack. Paint the Active palette
        # unconditionally so xterm stealing focus doesn't dim the highlight.
        selected = bool(option.state & option.state.State_Selected)
        if selected:
            painter.fillRect(option.rect, option.palette.highlight())
            text_color = option.palette.highlightedText().color()
            # Thin accent stripe on the left edge for extra glance-ability.
            # Uses highlightedText for contrast against the highlight bg.
            stripe_rect = QRect(
                option.rect.left(), option.rect.top(),
                self.ACTIVE_STRIPE_W, option.rect.height(),
            )
            painter.fillRect(stripe_rect, option.palette.highlightedText())
        else:
            painter.fillRect(option.rect, option.palette.base())
            text_color = option.palette.text().color()

        repo: Repo = index.data(ROLE_REPO)
        branch: str | None = index.data(ROLE_BRANCH)
        status: str = index.data(ROLE_STATUS) or ""

        rect = option.rect.adjusted(self.PADDING_X, 4, -self.PADDING_X, -4)

        # Repo name (bold) on line 1.
        name_font = QFont(option.font)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(QPen(text_color))
        name_rect = QRect(rect.left(), rect.top(), rect.width(), rect.height() // 2)
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, repo.name if repo else "")

        # Branch subtitle on line 2.
        sub_font = QFont(option.font)
        sub_font.setPointSizeF(option.font.pointSizeF() * 0.9)
        painter.setFont(sub_font)
        painter.setPen(QPen(text_color.lighter(130) if text_color.lightness() < 128 else text_color.darker(140)))
        sub_text = branch if branch else "(detached)" if repo else ""
        sub_rect = QRect(rect.left(), rect.top() + rect.height() // 2, rect.width(), rect.height() // 2)
        painter.drawText(sub_rect, Qt.AlignLeft | Qt.AlignVCenter, sub_text)

        # Status dot — color-coded: red for "needs attention", green for
        # "done". One state per repo (each event supersedes the previous).
        color = self.STATUS_COLORS.get(status)
        if color is not None:
            dot_d = 10
            dot_rect = QRect(
                rect.right() - dot_d,
                rect.top() + (rect.height() - dot_d) // 2,
                dot_d,
                dot_d,
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.drawEllipse(dot_rect)

        painter.restore()


class RepoSidebar(QWidget):
    """The left-hand column: scrollable repo list + '+ Add Repo' at the bottom."""

    repo_selected = Signal(Repo)
    repo_added = Signal(Repo)
    repo_removed = Signal(str)  # emits the removed path
    reload_requested = Signal(Repo)  # user asked to respawn the terminal

    def __init__(self, store: RepoStore, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._model = RepoListModel(store, self)

        self._view = QListView(self)
        self._view.setModel(self._model)
        self._view.setItemDelegate(RepoDelegate(self._view))
        self._view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._view.setSelectionMode(QAbstractItemView.SingleSelection)
        self._view.setUniformItemSizes(True)
        self._view.selectionModel().currentChanged.connect(self._on_current_changed)
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)

        self._add_btn = QPushButton("+ Add Repo", self)
        self._add_btn.clicked.connect(self._on_add_clicked)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._view, 1)
        lay.addWidget(self._add_btn, 0)

        self.setMinimumWidth(200)
        self.setMaximumWidth(320)

        self._model.reload()
        self._model.refresh_branches()

    # ── public API ──

    @property
    def model(self) -> RepoListModel:
        return self._model

    def select_path(self, path: str) -> None:
        row = self._model.index_of(path)
        if row >= 0:
            idx = self._model.index(row)
            self._view.setCurrentIndex(idx)

    def refresh_branches(self) -> None:
        self._model.refresh_branches()

    def set_status(self, path: str, status: str) -> None:
        self._model.set_status(path, status)

    def clear_status(self, path: str) -> None:
        self._model.clear_status(path)

    # ── signals ──

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        repo = self._model.repo_at(current.row()) if current.isValid() else None
        if repo is not None:
            self._model.clear_status(repo.path)
            self.repo_selected.emit(repo)

    def _on_add_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Add repo directory", os.path.expanduser("~"))
        if not path:
            return
        if self._model.add_repo(path):
            # Select the just-added row.
            self.select_path(path)
            added = self._model.repo_at(len(self._store.repos) - 1)
            if added is not None:
                self.repo_added.emit(added)

    def _on_context_menu(self, pos: QPoint) -> None:
        idx = self._view.indexAt(pos)
        if not idx.isValid():
            return
        repo = self._model.repo_at(idx.row())
        if repo is None:
            return

        menu = QMenu(self)
        reload_act = QAction("Reload terminal", menu)
        reload_act.setToolTip("Respawn xterm to pick up new settings. Loses in-flight shell state.")
        reload_act.triggered.connect(lambda _=False, r=repo: self._confirm_reload(r))
        menu.addAction(reload_act)

        menu.addSeparator()
        remove_act = QAction("Remove from sidebar", menu)
        remove_act.triggered.connect(lambda _=False, r=repo, row=idx.row(): self._confirm_remove(r, row))
        menu.addAction(remove_act)

        menu.exec(self._view.viewport().mapToGlobal(pos))

    def _confirm_reload(self, repo: Repo) -> None:
        ans = QMessageBox.question(
            self,
            "Reload terminal",
            f"Respawn the terminal for {repo.name}?\n\n"
            "The running shell (and any active Claude session) will be killed. "
            "If Claude was mid-response, that response is lost — but the "
            "conversation transcript is preserved and will resume on next launch.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            self.reload_requested.emit(repo)

    def _confirm_remove(self, repo: Repo, row: int) -> None:
        ans = QMessageBox.question(
            self,
            "Remove from sidebar",
            f"Remove {repo.name} from ccwork?\n\n"
            "The repo directory on disk is untouched — this only removes it "
            "from the sidebar list.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            self._model.remove_repo_at(row)
            self.repo_removed.emit(repo.path)
