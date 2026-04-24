"""Tests for terminal_session argv construction."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.core import terminal_session
from src.core.repo_store import Repo


def _split_on_dash_e(argv: list[str]) -> tuple[list[str], list[str]]:
    """Return (xterm_flags_before_-e, inner_cmd_after_-e)."""
    idx = argv.index("-e")
    return argv[:idx], argv[idx + 1 :]


@pytest.fixture
def tmp_claude(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    return tmp_path


def _with_transcript(cfg: Path, repo_path: str) -> None:
    slug = repo_path.translate(str.maketrans({"/": "-", "_": "-", ".": "-"}))
    pd = cfg / "projects" / slug
    pd.mkdir(parents=True)
    (pd / "t.jsonl").write_text("{}\n")


def test_session_name_is_stable() -> None:
    assert terminal_session.tmux_session_name("/a/b") == "ccwork-a-b"
    assert terminal_session.tmux_session_name("/a_b.c") == "ccwork-a-b-c"


def test_no_transcript_uses_interactive_shell(tmp_claude: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    spec = terminal_session.build_session(Repo(path="/fake/repo"), auto_resume=True)
    flags, inner = _split_on_dash_e(spec.argv)
    assert inner == ["/bin/bash", "-i"]
    assert "-fs" in flags  # settings flags are prepended before -e
    assert spec.env == {"CCWORK_GUI": "1"}
    assert spec.cwd == "/fake/repo"


def test_transcript_triggers_continue(tmp_claude: Path) -> None:
    _with_transcript(tmp_claude, "/fake/repo")
    spec = terminal_session.build_session(Repo(path="/fake/repo"), auto_resume=True)
    _, inner = _split_on_dash_e(spec.argv)
    assert inner == ["claude", "--continue"]


def test_auto_resume_off_ignores_transcript(tmp_claude: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _with_transcript(tmp_claude, "/fake/repo")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    spec = terminal_session.build_session(Repo(path="/fake/repo"), auto_resume=False)
    _, inner = _split_on_dash_e(spec.argv)
    assert inner == ["/bin/zsh", "-i"]


def test_persist_wraps_in_tmux_when_available(tmp_claude: Path) -> None:
    tmux = shutil.which("tmux")
    if not tmux:
        pytest.skip("tmux not installed")
    _with_transcript(tmp_claude, "/fake/repo")
    spec = terminal_session.build_session(Repo(path="/fake/repo", persist=True), auto_resume=True)
    _, inner = _split_on_dash_e(spec.argv)
    assert inner[0] == tmux
    assert inner[1:5] == ["new", "-A", "-s", "ccwork-fake-repo"]
    assert inner[5] == "claude --continue"


def test_persist_degrades_when_tmux_missing(tmp_claude: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force shutil.which("tmux") to return None.
    orig_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "tmux" else orig_which(name))
    monkeypatch.setenv("SHELL", "/bin/bash")
    spec = terminal_session.build_session(Repo(path="/fake/repo", persist=True), auto_resume=True)
    _, inner = _split_on_dash_e(spec.argv)
    assert inner == ["/bin/bash", "-i"]


def test_settings_flags_are_applied(tmp_claude: Path) -> None:
    from src.core.settings import XtermSettings
    x = XtermSettings(font_size=8, scrollback=12345, scrollbar="none", jump_scroll=False)
    spec = terminal_session.build_session(Repo(path="/fake/repo"), xterm_settings=x)
    flags, _ = _split_on_dash_e(spec.argv)
    assert "-fs" in flags and flags[flags.index("-fs") + 1] == "8"
    assert "-sl" in flags and flags[flags.index("-sl") + 1] == "12345"
    assert "+sb" in flags
    assert "-j" not in flags


def test_gui_marker_toggleable(tmp_claude: Path) -> None:
    spec = terminal_session.build_session(Repo(path="/fake/repo"), gui_marker=False)
    assert spec.env == {}
