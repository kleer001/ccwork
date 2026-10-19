"""Right-click opens the row menu without activating the row; left-click activates."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.core.repo_store import Repo, RepoStore
from src.ui.repo_sidebar import RepoSidebar


def _sidebar(tmp_path: Path) -> tuple[RepoSidebar, list[Repo]]:
    store = RepoStore(config_path=tmp_path / "repos.json")
    repos = [Repo(path=str(tmp_path / "a")), Repo(path=str(tmp_path / "b"))]
    store.repos = repos
    store.save()  # RepoSidebar reloads the store from disk
    sidebar = RepoSidebar(store)
    sidebar.resize(300, 400)
    sidebar.show()
    return sidebar, repos


def _row_center(sidebar: RepoSidebar, row: int) -> QPoint:
    view = sidebar._view
    return view.visualRect(view.model().index(row, 0)).center()


def test_right_click_opens_menu_without_activating(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    sidebar, _ = _sidebar(tmp_path)
    selected: list[Repo] = []
    clicked: list[Repo] = []
    sidebar.repo_selected.connect(selected.append)
    sidebar.repo_clicked.connect(clicked.append)
    menus: list[Repo] = []

    class _Menu:
        def exec(self, pos: QPoint) -> None:
            pass

    def _build(repo: Repo, row: int) -> _Menu:
        menus.append(repo)
        return _Menu()

    monkeypatch.setattr(sidebar, "_build_context_menu", _build)

    pos = _row_center(sidebar, 1)
    viewport = sidebar._view.viewport()
    QTest.mouseClick(viewport, Qt.RightButton, Qt.NoModifier, pos)
    QApplication.sendEvent(
        viewport, QContextMenuEvent(QContextMenuEvent.Mouse, pos, viewport.mapToGlobal(pos))
    )

    assert selected == [] and clicked == []
    assert not sidebar._view.currentIndex().isValid()
    assert menus == [sidebar.model.repo_at(1)]


def test_left_click_activates(qapp: QApplication, tmp_path: Path) -> None:
    sidebar, _ = _sidebar(tmp_path)
    selected: list[Repo] = []
    sidebar.repo_selected.connect(selected.append)
    QTest.mouseClick(sidebar._view.viewport(), Qt.LeftButton, Qt.NoModifier, _row_center(sidebar, 1))
    assert selected == [sidebar.model.repo_at(1)]
