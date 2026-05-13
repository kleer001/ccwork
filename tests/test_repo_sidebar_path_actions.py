"""Tests for the path-action items in the sidebar row context menu.

Covers the `_copy_path` and `_open_in_file_manager` helpers and the
disabled-state contract of "Open in file manager" when xdg-open isn't
on PATH. Menu construction is exercised via `_build_context_menu`
directly so no real right-click event has to be synthesized.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from src.core.repo_store import Repo, RepoStore
from src.ui import repo_sidebar
from src.ui.repo_sidebar import RepoSidebar


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _sidebar_with(repo_path: str, cfg_path: Path) -> tuple[RepoSidebar, Repo]:
    store = RepoStore(config_path=cfg_path)
    repo = Repo(path=repo_path)
    store.repos = [repo]
    sidebar = RepoSidebar(store)
    return sidebar, repo


def test_copy_path_puts_path_on_clipboard(qapp: QApplication, tmp_path: Path) -> None:
    sidebar, repo = _sidebar_with(str(tmp_path / "my-repo"), tmp_path / "repos.json")
    sidebar._copy_path(repo)
    assert QGuiApplication.clipboard().text() == repo.path


def test_copy_path_emits_path_copied_signal(qapp: QApplication, tmp_path: Path) -> None:
    sidebar, repo = _sidebar_with(str(tmp_path / "r"), tmp_path / "repos.json")
    received: list[str] = []
    sidebar.path_copied.connect(received.append)
    sidebar._copy_path(repo)
    assert received == [repo.path]


def test_copy_path_handles_paths_with_spaces(qapp: QApplication, tmp_path: Path) -> None:
    """No shell quoting is needed; the path goes raw to the clipboard.
    Lock that contract in so a future refactor can't regress it."""
    spaced = tmp_path / "has spaces in it"
    sidebar, repo = _sidebar_with(str(spaced), tmp_path / "repos.json")
    sidebar._copy_path(repo)
    assert QGuiApplication.clipboard().text() == str(spaced)
    assert " " in QGuiApplication.clipboard().text()


def test_open_in_file_manager_invokes_xdg_open(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sidebar, repo = _sidebar_with(str(tmp_path / "r"), tmp_path / "repos.json")
    calls: list[tuple[str, list[str]]] = []

    def recorder(program, arguments=None):
        calls.append((program, list(arguments or [])))
        return True

    monkeypatch.setattr(QProcess, "startDetached", recorder)
    sidebar._open_in_file_manager(repo)
    assert calls == [("xdg-open", [repo.path])]


def test_open_in_file_manager_disabled_when_xdg_open_missing(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probe is at menu-build time. With xdg-open absent the action is
    disabled and its tooltip names the missing package so the user knows
    what to install."""
    monkeypatch.setattr(repo_sidebar.shutil, "which", lambda cmd: None)
    sidebar, repo = _sidebar_with(str(tmp_path / "r"), tmp_path / "repos.json")
    menu = sidebar._build_context_menu(repo, row=0)
    actions = {a.text(): a for a in menu.actions() if a.text()}
    fm_act = actions["Open in file manager"]
    assert fm_act.isEnabled() is False
    assert "xdg-utils" in fm_act.toolTip()


def test_open_in_file_manager_enabled_when_xdg_open_present(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Companion to the disabled-case test — pin the enabled path so a
    future refactor of the probe can't silently break the happy case."""
    monkeypatch.setattr(repo_sidebar.shutil, "which", lambda cmd: "/usr/bin/xdg-open")
    sidebar, repo = _sidebar_with(str(tmp_path / "r"), tmp_path / "repos.json")
    menu = sidebar._build_context_menu(repo, row=0)
    actions = {a.text(): a for a in menu.actions() if a.text()}
    fm_act = actions["Open in file manager"]
    assert fm_act.isEnabled() is True


def test_context_menu_path_actions_appear_between_clone_and_badge(
    qapp: QApplication, tmp_path: Path
) -> None:
    """Order matters per spec: Reload → Clone → Open in FM → Copy path →
    sep → Set badge → Clear badge → sep → Remove. Lock the ordering so
    a future menu addition doesn't disrupt the path-group cluster."""
    sidebar, repo = _sidebar_with(str(tmp_path / "r"), tmp_path / "repos.json")
    menu = sidebar._build_context_menu(repo, row=0)
    labels = [a.text() for a in menu.actions()]
    # Strip the separator entries ("" labels) for ordering comparison.
    non_sep = [t for t in labels if t]
    assert non_sep == [
        "Reload terminal",
        "Clone this repo",
        "Open in file manager",
        "Copy path",
        "Set badge…",
        "Clear badge",
        "Remove from sidebar",
    ]
    # And there must be NO separator between Clone and Open in file manager
    # (the path-action group reads as one cluster with Clone). Two separators
    # total: one before Set badge, one before Remove.
    sep_positions = [i for i, a in enumerate(menu.actions()) if a.isSeparator()]
    assert len(sep_positions) == 2
