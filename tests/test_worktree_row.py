"""A row on a linked worktree shows `<main name> ↳ <branch>` on line 2 and in
the title tab. Spec: `docs/specs/worktree.md` section 4."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from src.core import repo_store
from src.core.repo_store import Repo, RepoStore
from src.ui.badge_theme import WORKTREE_GLYPH, load_badge_theme
from src.ui.repo_delegate import REPO_LINE_SEP, WORKTREE_LINE_SEP, fit_line
from src.ui.repo_model import ROLE_WORKTREE_OF
from src.ui.repo_sidebar import RepoSidebar
from src.ui.title_tab import TitleTab

from tests.gitrepo import git, seed


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    return seed(Path(os.path.realpath(tmp_path)) / "proj", {"README": "seed\n"})


@pytest.fixture
def sibling(main_repo: Path) -> Path:
    wt = main_repo.parent / "proj-fix-a"
    git("-C", str(main_repo), "worktree", "add", "-q", "-b", "fix/a", str(wt), "HEAD")
    return wt


class _TextPainter(QPainter):
    def __init__(self, image: QImage) -> None:
        super().__init__(image)
        self.texts: list[str] = []

    def drawText(self, *args) -> None:  # noqa: N802 — Qt's name
        self.texts.append(next(a for a in args if isinstance(a, str)))
        super().drawText(*args)


def _painted(sidebar: RepoSidebar, row: int) -> str:
    image = QImage(600, 100, QImage.Format_ARGB32)
    painter = _TextPainter(image)
    option = QStyleOptionViewItem()
    option.rect = image.rect()
    option.palette = sidebar.palette()
    option.font = sidebar.font()
    sidebar._delegate.paint(painter, option, sidebar.model.index(row))
    painter.end()
    return "".join(painter.texts)


def _sidebar(tmp_path: Path, paths: list[Path]) -> RepoSidebar:
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path=str(p)) for p in paths]
    store.save()  # RepoSidebar reloads the store from disk
    sidebar = RepoSidebar(store)
    sidebar.refresh_branches()
    return sidebar


def test_main_name_of_a_linked_worktree(main_repo: Path, sibling: Path) -> None:
    claude_wt = main_repo / ".claude" / "worktrees" / "x"
    git("-C", str(main_repo), "worktree", "add", "-q", "-b", "worktree-x", str(claude_wt), "HEAD")
    (main_repo / "sub").mkdir()

    assert repo_store.worktree_main_name(sibling) == "proj"
    assert repo_store.worktree_main_name(claude_wt) == "proj"
    assert repo_store.worktree_main_name(main_repo) == ""
    assert repo_store.worktree_main_name(main_repo / "sub") == ""
    assert repo_store.worktree_main_name(main_repo.parent) == ""


def test_role_marks_only_the_worktree_row(
    qapp: QApplication, tmp_path: Path, main_repo: Path, sibling: Path
) -> None:
    sidebar = _sidebar(tmp_path, [main_repo, sibling])
    assert sidebar.model.index(0).data(ROLE_WORKTREE_OF) == ""
    assert sidebar.model.index(1).data(ROLE_WORKTREE_OF) == "proj"


def test_line_two_uses_the_worktree_glyph(
    qapp: QApplication, tmp_path: Path, main_repo: Path, sibling: Path
) -> None:
    sidebar = _sidebar(tmp_path, [main_repo, sibling])
    assert f"proj{REPO_LINE_SEP}main" in _painted(sidebar, 0)
    assert f"proj{WORKTREE_LINE_SEP}fix/a" in _painted(sidebar, 1)
    assert WORKTREE_GLYPH == "↳"


def test_rebind_into_a_worktree_marks_the_row_at_once(
    qapp: QApplication, tmp_path: Path, main_repo: Path, sibling: Path
) -> None:
    sidebar = _sidebar(tmp_path, [main_repo])
    row_id = sidebar.model.repo_at(0).id

    sidebar.rebind(row_id, str(sibling), follow=True)

    assert sidebar.model.index(0).data(ROLE_WORKTREE_OF) == "proj"
    assert f"proj{WORKTREE_LINE_SEP}fix/a" in _painted(sidebar, 0)


def test_added_worktree_folder_is_marked(
    qapp: QApplication, tmp_path: Path, main_repo: Path, sibling: Path
) -> None:
    sidebar = _sidebar(tmp_path, [main_repo])
    sidebar.model.add_repo(str(sibling))
    assert sidebar.model.index(1).data(ROLE_WORKTREE_OF) == "proj"


def test_duplicate_worktree_rows_keep_their_numeral(
    qapp: QApplication, tmp_path: Path, main_repo: Path, sibling: Path
) -> None:
    sidebar = _sidebar(tmp_path, [main_repo])
    sidebar.model.add_repo(str(sibling))
    sidebar.model.add_repo(str(sibling))
    assert f"proj (II){WORKTREE_LINE_SEP}fix/a" in _painted(sidebar, 2)


def test_fit_line_elides_the_branch_first_with_the_worktree_glyph(qapp: QApplication) -> None:
    fm = TitleTab().fontMetrics()
    head = f"proj{WORKTREE_LINE_SEP}"
    full = fit_line(fm, "proj", "fix/a-long-branch", 10_000, WORKTREE_LINE_SEP)
    assert full == f"{head}fix/a-long-branch"
    width = fm.horizontalAdvance(head) + fm.horizontalAdvance("fix/a-lo")
    cut = fit_line(fm, "proj", "fix/a-long-branch", width, WORKTREE_LINE_SEP)
    assert cut.startswith(head) and cut.endswith("…")


def test_title_tab_shows_the_worktree_mark(qapp: QApplication) -> None:
    tab = TitleTab()
    tab.set_repo("proj", "fix/a", "Fix the flash timing", worktree=True)
    assert tab._head == f"proj{WORKTREE_LINE_SEP}fix/a"


def test_badges_toml_sets_the_worktree_glyph_and_color(tmp_path: Path) -> None:
    path = tmp_path / "badges.toml"
    path.write_text('worktree_glyph = "⑂"\nworktree_color = "#2aa198"\n')
    theme = load_badge_theme(path)
    assert theme.worktree_glyph == "⑂"
    assert theme.worktree_color.name() == "#2aa198"
    assert load_badge_theme(tmp_path / "none.toml").worktree_color is None


def test_worktree_color_paints_the_glyph_as_its_own_run(
    qapp: QApplication, tmp_path: Path, main_repo: Path, sibling: Path, monkeypatch
) -> None:
    from PySide6.QtGui import QColor
    from src.ui import repo_delegate
    monkeypatch.setattr(repo_delegate, "WORKTREE_COLOR", QColor("#2aa198"))
    sidebar = _sidebar(tmp_path, [sibling])
    image = QImage(600, 100, QImage.Format_ARGB32)
    painter = _TextPainter(image)
    option = QStyleOptionViewItem()
    option.rect = image.rect()
    option.palette = sidebar.palette()
    option.font = sidebar.font()
    sidebar._delegate.paint(painter, option, sidebar.model.index(0))
    painter.end()
    runs = ["proj  ", WORKTREE_GLYPH, "  fix/a"]
    assert runs in [painter.texts[i:i + 3] for i in range(len(painter.texts))]
