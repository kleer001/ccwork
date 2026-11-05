"""Make worktree rebuilds the source folder's venv and node_modules in the
new worktree's first terminal. Spec: `docs/specs/worktree.md` 5.5."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication, QLineEdit

from src.core import worktree_setup
from src.core.repo_store import Repo, RepoStore
from src.core.worktree import make_worktree, worktree_plan, worktree_source
from src.core.worktree_setup import UV_MISSING, setup_commands
from src.ui.repo_sidebar import RepoSidebar
from src.ui.worktree_dialog import WorktreeDialog

from tests.gitrepo import commit, seed

BASHRC = Path(__file__).resolve().parents[1] / "bin" / "ccwork-bashrc"


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    return seed(Path(os.path.realpath(tmp_path)) / "proj",
                {".gitignore": ".venv/\nvenv/\nnode_modules/\n", "README": "seed\n"})


def _new_worktree(repo: Path) -> Path:
    return Path(make_worktree(worktree_plan(worktree_source(str(repo)), "x")))


def _fake_venv(folder: Path, name: str = ".venv", key: str = "version") -> None:
    (folder / name).mkdir()
    (folder / name / "pyvenv.cfg").write_text(f"home = /usr/bin\n{key} = 3.12.3\n")


@pytest.fixture
def uv(monkeypatch) -> str:
    monkeypatch.setattr(worktree_setup.shutil, "which", lambda cmd: "/opt/uv" if cmd == "uv" else None)
    return "/opt/uv"


def test_nothing_installs_with_no_venv_and_no_node_modules(main_repo: Path) -> None:
    assert setup_commands(str(main_repo), str(_new_worktree(main_repo))) == ""


def test_venv_with_uv_lock_runs_uv_sync(main_repo: Path, uv: str) -> None:
    _fake_venv(main_repo)
    commit(main_repo, {"uv.lock": ""}, "uv.lock")
    commit(main_repo, {"requirements.txt": ""}, "requirements.txt")
    wt = _new_worktree(main_repo)
    venv = shlex.quote(str(wt / ".venv"))
    assert setup_commands(str(main_repo), str(wt)) == (
        f"/opt/uv venv --python 3.12.3 {venv} && VIRTUAL_ENV={venv} /opt/uv sync --active")


def test_a_uv_made_venv_gives_its_version_info(main_repo: Path, uv: str) -> None:
    _fake_venv(main_repo, name="venv", key="version_info")
    commit(main_repo, {"uv.lock": ""}, "uv.lock")
    wt = _new_worktree(main_repo)
    assert setup_commands(str(main_repo), str(wt)).startswith(
        f"/opt/uv venv --python 3.12.3 {shlex.quote(str(wt / 'venv'))} && ")


def test_no_uv_prints_the_line_and_makes_no_venv(main_repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(worktree_setup.shutil, "which", lambda cmd: None)
    _fake_venv(main_repo)
    assert setup_commands(str(main_repo), str(_new_worktree(main_repo))) == (
        f"echo {shlex.quote(UV_MISSING)}")


@pytest.mark.parametrize("lock, command", [
    ("package-lock.json", "npm ci"),
    ("pnpm-lock.yaml", "pnpm install --frozen-lockfile"),
    ("yarn.lock", "yarn install --frozen-lockfile"),
])
def test_node_modules_install_by_lock_file(main_repo: Path, lock: str, command: str) -> None:
    (main_repo / "node_modules").mkdir()
    commit(main_repo, {lock: "{}\n"}, lock)
    assert setup_commands(str(main_repo), str(_new_worktree(main_repo))) == command


def test_node_modules_with_no_lock_file_installs_nothing(main_repo: Path) -> None:
    (main_repo / "node_modules").mkdir()
    assert setup_commands(str(main_repo), str(_new_worktree(main_repo))) == ""


@pytest.mark.parametrize("files, install", [
    (["requirements.txt", "pyproject.toml"], "-r {wt}/requirements.txt"),
    (["pyproject.toml"], "-r {wt}/pyproject.toml --all-extras"),
])
def test_a_venv_with_no_uv_lock_installs_the_declared_dependencies(
    main_repo: Path, uv: str, files: list[str], install: str
) -> None:
    _fake_venv(main_repo)
    for name in files:
        commit(main_repo, {name: ""}, name)
    wt = _new_worktree(main_repo)
    venv = shlex.quote(str(wt / ".venv"))
    assert setup_commands(str(main_repo), str(wt)) == (
        f"/opt/uv venv --python 3.12.3 {venv} && /opt/uv pip install "
        f"--python {shlex.quote(str(wt / '.venv' / 'bin' / 'python'))} {install.format(wt=wt)}")


def test_a_venv_with_no_declaration_gets_an_empty_venv(main_repo: Path, uv: str) -> None:
    _fake_venv(main_repo)
    (main_repo / "requirements.txt").write_text("")  # uncommitted: not in the worktree
    wt = _new_worktree(main_repo)
    assert setup_commands(str(main_repo), str(wt)) == (
        f"/opt/uv venv --python 3.12.3 {shlex.quote(str(wt / '.venv'))}")


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_the_setup_makes_a_venv_with_the_source_python(main_repo: Path) -> None:
    subprocess.run(["uv", "venv", "-q", "--python", "3.12", str(main_repo / ".venv")], check=True)
    commit(main_repo, {"requirements.txt": ""}, "requirements.txt")
    wt = _new_worktree(main_repo)
    cmd = setup_commands(str(main_repo), str(wt))
    subprocess.run(["bash", "-c", cmd], check=True, capture_output=True, timeout=60)
    version = [l for l in (wt / ".venv" / "pyvenv.cfg").read_text().splitlines()
               if l.startswith("version_info")]
    source = [l for l in (main_repo / ".venv" / "pyvenv.cfg").read_text().splitlines()
              if l.startswith("version_info")]
    assert version == source


def test_make_worktree_passes_the_setup_to_the_first_terminal(
    qapp: QApplication, tmp_path: Path, main_repo: Path, uv: str, monkeypatch
) -> None:
    (main_repo / "node_modules").mkdir()
    commit(main_repo, {"package-lock.json": "{}\n"}, "package-lock.json")
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path=str(main_repo))]
    store.save()
    sidebar = RepoSidebar(store)
    monkeypatch.setattr(WorktreeDialog, "exec", lambda self: (self.findChild(QLineEdit).setText("fix/a"), 1)[1])
    seen = []
    sidebar.repo_selected.connect(lambda r: seen.append(sidebar.take_spawn_env(r.id)))
    sidebar._make_worktree(sidebar.model.repo_at(0))
    assert seen == [{"CCWORK_SETUP_CMD": "npm ci"}]


def test_bashrc_runs_the_setup_once_in_view(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path), "PATH": os.environ["PATH"], "CCWORK_SETUP_CMD": "echo ran"}
    out = subprocess.run(["bash", "--rcfile", str(BASHRC), "-i", "-c", 'echo "[${CCWORK_SETUP_CMD:-}]"'],
                         env=env, capture_output=True, text=True, timeout=10).stdout
    assert out.splitlines()[-3:] == ["+ echo ran", "ran", "[]"]
