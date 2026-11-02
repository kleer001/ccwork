"""Badge pop: a new status badge grows past full size and settles."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.core.hook_server import EVENT_STOP, EVENT_USER_PROMPT_SUBMIT
from src.core.repo_store import Repo, RepoStore
from src.ui.repo_sidebar import POP_MS, RepoSidebar


def _sidebar(tmp_path: Path) -> tuple[RepoSidebar, Repo]:
    store = RepoStore(config_path=tmp_path / "repos.json")
    repo = Repo(path=str(tmp_path / "a"))
    store.repos = [repo]
    store.save()  # RepoSidebar reloads the store from disk
    return RepoSidebar(store), repo


def test_new_badge_pops_to_about_120_percent_then_settles(
    qapp: QApplication, tmp_path: Path
) -> None:
    sidebar, repo = _sidebar(tmp_path)
    sidebar.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, repo.id)
    sidebar.apply_hook_event(EVENT_STOP, repo.id)
    anim = sidebar._pops[repo.id]

    scales = []
    for ms in range(0, POP_MS, 10):
        anim.setCurrentTime(ms)
        scales.append(sidebar._delegate.pop_scale[repo.id])
    assert scales[0] == 0.0
    assert 1.15 < max(scales) < 1.25
    assert abs(scales[-1] - 1.0) < 0.05

    anim.setCurrentTime(POP_MS)
    assert repo.id not in sidebar._delegate.pop_scale
    assert repo.id not in sidebar._pops


def test_same_badge_again_does_not_pop(qapp: QApplication, tmp_path: Path) -> None:
    sidebar, repo = _sidebar(tmp_path)
    sidebar.apply_hook_event(EVENT_STOP, repo.id)
    sidebar._pops[repo.id].setCurrentTime(POP_MS)
    sidebar.apply_hook_event(EVENT_STOP, repo.id)
    assert repo.id not in sidebar._pops
