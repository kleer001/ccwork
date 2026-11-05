"""Make worktree copies the source folder's small ignored files into the new
worktree, and the new terminal prints what it copied and what it did not.
Spec: `docs/specs/worktree.md` 5.4."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication, QLineEdit

from src.core.repo_store import Repo, RepoStore
from src.core.worktree import make_worktree, worktree_plan, worktree_source
from src.core.worktree_files import COPY_MAX_BYTES, CopyReport, copy_ignored
from src.ui.repo_sidebar import RepoSidebar
from src.ui.worktree_dialog import WorktreeDialog

from tests.gitrepo import seed

BASHRC = Path(__file__).resolve().parents[1] / "bin" / "ccwork-bashrc"


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    return seed(Path(os.path.realpath(tmp_path)) / "proj", {
        ".gitignore": ".env\n*.bin\ntmp/\nlocal.cfg\nlink\n.claude/settings.local.json\n",
        "src/app.py": "print()\n",
    })


def _new_worktree(repo: Path, name: str = "x") -> Path:
    return Path(make_worktree(worktree_plan(worktree_source(str(repo)), name)))


def test_small_files_are_copied_with_mode_and_times(main_repo: Path) -> None:
    env = main_repo / ".env"
    env.write_text("KEY=1\n")
    env.chmod(0o600)
    os.utime(env, (1_000_000, 1_000_000))
    (main_repo / "src" / "local.cfg").write_text("a=1\n")
    wt = _new_worktree(main_repo)
    report = copy_ignored(str(main_repo), str(wt))
    assert (wt / ".env").read_text() == "KEY=1\n"
    assert (wt / ".env").stat().st_mode & 0o777 == 0o600
    assert (wt / ".env").stat().st_mtime == 1_000_000
    assert (wt / "src" / "local.cfg").read_text() == "a=1\n"
    assert report.copied == 2 and report.skipped == [] and report.failed == []


def test_folders_big_files_links_and_claude_settings_stay_behind(main_repo: Path) -> None:
    (main_repo / "tmp").mkdir()
    (main_repo / "tmp" / "result.csv").write_text("1\n")
    (main_repo / "model.bin").write_bytes(b"\0" * (COPY_MAX_BYTES + 1))
    (main_repo / "small.bin").write_bytes(b"\0" * COPY_MAX_BYTES)
    (main_repo / "link").symlink_to("src/app.py")
    (main_repo / ".claude").mkdir()
    (main_repo / ".claude" / "settings.local.json").write_text("{}\n")
    wt = _new_worktree(main_repo)
    report = copy_ignored(str(main_repo), str(wt))
    assert not (wt / "tmp").exists()
    assert not (wt / "model.bin").exists()
    assert (wt / "small.bin").stat().st_size == COPY_MAX_BYTES
    assert not (wt / "link").is_symlink() and not (wt / "link").exists()
    assert not (wt / ".claude" / "settings.local.json").exists()
    assert report.copied == 1
    assert sorted(report.skipped) == [("link", None), ("model.bin", COPY_MAX_BYTES + 1)]


def test_a_folder_that_ignores_itself_stays_behind(main_repo: Path) -> None:
    venv = main_repo / ".venv"
    venv.mkdir()
    (venv / ".gitignore").write_text("*\n")
    (venv / "pyvenv.cfg").write_text("version_info = 3.12.3\n")
    wt = _new_worktree(main_repo)
    report = copy_ignored(str(main_repo), str(wt))
    assert not (wt / ".venv").exists()
    assert report.copied == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file with mode 0")
def test_a_failed_copy_is_reported_and_the_others_go_on(main_repo: Path) -> None:
    (main_repo / ".env").write_text("KEY=1\n")
    (main_repo / "src" / "local.cfg").write_text("a=1\n")
    wt = _new_worktree(main_repo)
    (main_repo / "src" / "local.cfg").chmod(0)
    try:
        report = copy_ignored(str(main_repo), str(wt))
    finally:
        (main_repo / "src" / "local.cfg").chmod(0o644)
    assert (wt / ".env").exists()
    assert report.copied == 1
    assert [name for name, _ in report.failed] == ["src/local.cfg"]
    assert "Permission denied" in report.failed[0][1]


def test_report_text() -> None:
    report = CopyReport(copied=4, skipped=[("models/base.safetensors", 6_900_000_000),
                                           ("data/index.json", 130_000_000), ("link", None)],
                        failed=[("conf/a.cfg", "Permission denied")])
    assert report.text() == (
        "Copied 4 ignored files.\n"
        "Not copied (over 1 MiB or a link):\n"
        "  models/base.safetensors   6.9 GB\n"
        "  data/index.json           130 MB\n"
        "  link                      link\n"
        "Could not copy conf/a.cfg: Permission denied"
    )


def test_report_lists_ten_names_per_section_and_hides_control_characters() -> None:
    report = CopyReport(skipped=[(f"f{i:02}", 2_000_000) for i in range(12)],
                        failed=[(f"e{i:02}\x1b]0;x\x07", "denied") for i in range(11)])
    lines = report.text().splitlines()
    assert "  f09   2.0 MB" in lines and not any("f10" in l for l in lines)
    assert "  and 2 more" in lines
    assert "Could not copy e09?]0;x?: denied" in lines
    assert lines[-1] == "Could not copy 1 more files."
    assert "\x1b" not in report.text()


def test_report_text_one_file_and_nothing() -> None:
    assert CopyReport(copied=1).text() == "Copied 1 ignored file."
    assert CopyReport().text() == ""


def test_make_worktree_passes_the_report_to_the_first_terminal(
    qapp: QApplication, tmp_path: Path, main_repo: Path, monkeypatch
) -> None:
    (main_repo / ".env").write_text("KEY=1\n")
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path=str(main_repo))]
    store.save()
    sidebar = RepoSidebar(store)
    monkeypatch.setattr(WorktreeDialog, "exec", lambda self: (self.findChild(QLineEdit).setText("fix/a"), 1)[1])
    seen = []
    sidebar.repo_selected.connect(lambda r: seen.append(sidebar.take_spawn_env(r.id)))
    sidebar._make_worktree(sidebar.model.repo_at(0))
    assert seen == [{"CCWORK_NOTICE": "Copied 1 ignored file."}]
    assert (main_repo.parent / "proj-fix-a" / ".env").read_text() == "KEY=1\n"
    assert sidebar.take_spawn_env(sidebar.model.repo_at(1).id) is None


def test_bashrc_prints_the_notice_once(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path), "PATH": os.environ["PATH"], "CCWORK_NOTICE": "Copied 1 ignored file."}
    out = subprocess.run(["bash", "--rcfile", str(BASHRC), "-i", "-c", 'echo "[${CCWORK_NOTICE:-}]"'],
                         env=env, capture_output=True, text=True, timeout=10).stdout
    assert out.splitlines()[-2:] == ["Copied 1 ignored file.", "[]"]
