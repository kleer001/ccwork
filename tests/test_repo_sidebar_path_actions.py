"""Tests for the path-action items in the sidebar row context menu.

Covers the `_copy_path`, `_open_in_file_manager`, and rebind helpers, plus
the disabled-state contract of "Open in file manager" when xdg-open isn't
on PATH. Menu construction is exercised via `_build_context_menu`
directly so no real right-click event has to be synthesized.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from src.core.repo_store import Repo, RepoStore
from src.ui import repo_sidebar
from src.ui.repo_sidebar import ROLE_PATH_MISSING, RepoSidebar


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
    Rebind to… → sep → Set badge → Clear badge → sep → Remove. Lock the
    ordering so a future menu addition doesn't disrupt the path-group
    cluster."""
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
        "Rebind to…",
        "Set badge…",
        "Clear badge",
        "Remove from sidebar",
    ]
    # And there must be NO separator between Clone and Open in file manager
    # (the path-action group reads as one cluster with Clone). Two separators
    # total: one before Set badge, one before Remove.
    sep_positions = [i for i, a in enumerate(menu.actions()) if a.isSeparator()]
    assert len(sep_positions) == 2


# ── Rebind + path-missing ────────────────────────────────────────────────


def _git_init(path: Path) -> None:
    """Initialize a real git repo at `path` so is_git_root() succeeds.
    Tests that exercise the rebind validation gate need an honest git
    working tree, not a mocked one — otherwise we'd be testing the mock."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(path)],
        check=True, capture_output=True,
    )


def _persisted_sidebar(repo_paths: list[str], cfg_path: Path) -> tuple[RepoSidebar, RepoStore]:
    """Build a sidebar from a store whose contents are persisted to disk
    first. RepoSidebar.__init__ calls model.reload(), which reads the
    config file — so a freshly-assigned `store.repos = [...]` gets wiped
    if we don't save() before constructing the widget. Existing tests
    in this file dodge the issue by never reading from the model after
    construction; new model-state tests need the data to survive."""
    store = RepoStore(config_path=cfg_path)
    store.repos = [Repo(path=p) for p in repo_paths]
    store.save()
    sidebar = RepoSidebar(store)
    return sidebar, store


def test_path_missing_role_flips_when_dir_disappears(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The whole point of the new role: a row whose stored path no longer
    exists must paint as '(path missing)', not '(detached)'."""
    repo_dir = tmp_path / "alive"
    _git_init(repo_dir)
    sidebar, store = _persisted_sidebar([str(repo_dir)], tmp_path / "repos.json")
    sidebar.model.refresh_branches()
    idx = sidebar.model.index(0)
    assert sidebar.model.data(idx, ROLE_PATH_MISSING) is False

    # Simulate the user's `mv bruce_spec sphagnum` — the row's stored
    # path is now stale.
    repo_dir.rename(tmp_path / "renamed")
    sidebar.model.refresh_branches()
    assert sidebar.model.data(idx, ROLE_PATH_MISSING) is True


def test_rebind_repo_swaps_path_and_persists(
    qapp: QApplication, tmp_path: Path
) -> None:
    old_dir = tmp_path / "old_name"
    new_dir = tmp_path / "new_name"
    _git_init(old_dir)
    _git_init(new_dir)

    cfg = tmp_path / "repos.json"
    sidebar, store = _persisted_sidebar([str(old_dir)], cfg)
    repo_id = store.repos[0].id

    sidebar.model.rebind_repo(repo_id, str(new_dir))

    # In-memory: path and derived display_name reflect the new location.
    assert store.find_by_id(repo_id).path == str(new_dir)
    assert store.find_by_id(repo_id).display_name == "new_name"

    # On-disk: the new path round-trips through a fresh load.
    reloaded = RepoStore(config_path=cfg)
    reloaded.load()
    assert reloaded.find_by_id(repo_id).path == str(new_dir)

    # Caches: old path is evicted, new path is populated.
    assert str(old_dir) not in sidebar.model._branches
    assert str(old_dir) not in sidebar.model._path_missing
    assert sidebar.model._path_missing[str(new_dir)] is False


def test_rebind_repo_noop_when_same_path(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rebind to the current path must not call save() — otherwise an
    accidental double-click on the menu item rewrites repos.json for no
    reason and breaks any 'mtime unchanged → no work to do' assumptions a
    future external sync might rely on."""
    repo_dir = tmp_path / "stable"
    _git_init(repo_dir)
    sidebar, store = _persisted_sidebar([str(repo_dir)], tmp_path / "repos.json")
    repo_id = store.repos[0].id

    saves: list[int] = []
    real_save = store.save
    monkeypatch.setattr(store, "save", lambda: (saves.append(1), real_save())[1])

    sidebar.model.rebind_repo(repo_id, str(repo_dir))
    assert saves == []


def test_rebind_repo_updates_caches_for_new_path(
    qapp: QApplication, tmp_path: Path
) -> None:
    """After rebind, the new path's branch must be in _branches — otherwise
    the row sub-line would stay stale until the next refresh_branches()."""
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    _git_init(old_dir)
    _git_init(new_dir)
    # Make a commit on `new` so `git symbolic-ref --short HEAD` resolves
    # to "main" instead of None (empty repo has no HEAD ref yet).
    (new_dir / "README").write_text("hi\n")
    subprocess.run(["git", "-C", str(new_dir), "add", "README"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(new_dir), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "init"],
        check=True, capture_output=True,
    )

    sidebar, store = _persisted_sidebar([str(old_dir)], tmp_path / "repos.json")
    repo_id = store.repos[0].id

    sidebar.model.rebind_repo(repo_id, str(new_dir))
    assert sidebar.model._branches.get(str(new_dir)) == "main"
