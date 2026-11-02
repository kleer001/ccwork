"""Priority: a one-shot flag that flashes a working row when its next badge shows."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from src.core.hook_server import EVENT_PERMISSION_REQUEST, EVENT_SESSION_END, EVENT_STOP
from src.core.repo_store import Repo, RepoStore
from src.ui.badge_theme import PRIORITY_GLYPH, PRIORITY_TEXT
from src.ui.repo_model import ROLE_PRIORITY
from src.ui.repo_sidebar import FLASH_COUNT, RepoSidebar


def _sidebar(tmp_path: Path) -> tuple[RepoSidebar, list[Repo]]:
    store = RepoStore(config_path=tmp_path / "repos.json")
    repos = [Repo(path=str(tmp_path / "a")), Repo(path=str(tmp_path / "b"))]
    store.repos = repos
    store.save()  # RepoSidebar reloads the store from disk
    return RepoSidebar(store), repos


class _TextPainter(QPainter):
    """Keeps every string the delegate draws."""

    def __init__(self, image: QImage) -> None:
        super().__init__(image)
        self.texts: list[str] = []

    def drawText(self, *args) -> None:  # noqa: N802 — Qt's name
        self.texts.append(next(a for a in args if isinstance(a, str)))
        super().drawText(*args)


def _painted(sidebar: RepoSidebar, row: int) -> list[str]:
    image = QImage(400, 100, QImage.Format_ARGB32)
    painter = _TextPainter(image)
    option = QStyleOptionViewItem()
    option.rect = image.rect()
    option.palette = sidebar.palette()
    option.font = sidebar.font()
    sidebar._delegate.paint(painter, option, sidebar.model.index(row))
    painter.end()
    return painter.texts


def _menu_labels(sidebar: RepoSidebar, repo: Repo) -> list[str]:
    return [a.text() for a in sidebar._build_context_menu(repo, 0).actions()]


def test_menu_offers_priority_only_while_working(qapp: QApplication, tmp_path: Path) -> None:
    sidebar, (a, _) = _sidebar(tmp_path)
    labels = _menu_labels(sidebar, a)
    assert "Set priority" not in labels and "Clear priority" not in labels

    sidebar.set_working(a.id, True)
    assert _menu_labels(sidebar, a)[0] == "Set priority"

    sidebar.model.set_priority(a.id, True)
    assert _menu_labels(sidebar, a)[0] == "Clear priority"
    assert sidebar.model.index(0).data(ROLE_PRIORITY) is True


def test_badge_fires_priority_once_and_flashes_five_times(
    qapp: QApplication, tmp_path: Path
) -> None:
    sidebar, (a, b) = _sidebar(tmp_path)
    sidebar.set_working(a.id, True)
    sidebar.model.set_priority(a.id, True)

    sidebar.apply_hook_event(EVENT_STOP, b.id)  # another row: no effect
    assert sidebar.model.has_priority(a.id)
    assert not sidebar._delegate.flash_ids

    sidebar.apply_hook_event(EVENT_PERMISSION_REQUEST, a.id, {"tool_name": "Bash"})
    assert not sidebar.model.has_priority(a.id)
    assert sidebar._flash_timer.isActive()

    lit = [a.id in sidebar._delegate.flash_ids]  # the first phase shows at once
    for _ in range(2 * FLASH_COUNT - 1):
        sidebar._advance_flash()
        lit.append(a.id in sidebar._delegate.flash_ids)
    assert lit == [True, False] * FLASH_COUNT
    assert not sidebar._flash_timer.isActive()

    sidebar.apply_hook_event(EVENT_STOP, a.id)  # one-shot: no second flash
    assert not sidebar._flash_timer.isActive()


def test_session_end_clears_priority(qapp: QApplication, tmp_path: Path) -> None:
    sidebar, (a, _) = _sidebar(tmp_path)
    sidebar.set_working(a.id, True)
    sidebar.model.set_priority(a.id, True)
    sidebar.apply_hook_event(EVENT_SESSION_END, a.id, {"session_id": "s"})
    assert not sidebar.model.has_priority(a.id)
    assert not sidebar._flash_timer.isActive()


def test_priority_reads_as_words_on_the_status_line(qapp: QApplication, tmp_path: Path) -> None:
    sidebar, (a, _) = _sidebar(tmp_path)
    sidebar.set_working(a.id, True)
    sidebar.model.set_priority(a.id, True)
    texts = _painted(sidebar, 0)
    assert f" · {PRIORITY_GLYPH} {PRIORITY_TEXT}" in texts
    assert not any(t.startswith(PRIORITY_GLYPH) for t in texts)


def test_priority_glyph_leads_the_title_without_a_status_line(
    qapp: QApplication, tmp_path: Path
) -> None:
    sidebar, (a, _) = _sidebar(tmp_path)
    sidebar.set_working(a.id, True)
    sidebar.model.set_priority(a.id, True)
    sidebar._delegate.show_status_text = False
    texts = _painted(sidebar, 0)
    assert PRIORITY_GLYPH in texts
    assert not any(PRIORITY_TEXT in t for t in texts)
