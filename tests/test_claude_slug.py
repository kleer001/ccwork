"""Tests for claude_slug — parity with the bash slug logic in the old bin/claude."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from src.core import claude_slug


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/home/user/repo", "-home-user-repo"),
        ("/home/user/.dotfiles", "-home-user--dotfiles"),
        ("/home/user/my_project", "-home-user-my-project"),
        ("/a.b_c/d", "-a-b-c-d"),
        ("/", "-"),
        ("/x", "-x"),
    ],
)
def test_slug_matches_expected(path: str, expected: str) -> None:
    assert claude_slug.slug_for_path(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "/home/user/repo",
        "/home/user/.dotfiles",
        "/home/user/my_project.v2",
        "/var/tmp/a_b.c/d_e",
        "/",
    ],
)
def test_slug_parity_with_bash_sed(path: str) -> None:
    """The exact sed expression from the old bin/claude must match."""
    result = subprocess.run(
        ["sed", "s|[/_.]|-|g"],
        input=path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert claude_slug.slug_for_path(path) == result.stdout


def test_config_dir_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert claude_slug.claude_config_dir() == tmp_path


def test_config_dir_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert claude_slug.claude_config_dir() == Path.home() / ".claude"


def test_project_dir_composition(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert claude_slug.project_dir_for("/home/x/foo") == tmp_path / "projects" / "-home-x-foo"


def test_has_transcript_true(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    pdir = tmp_path / "projects" / "-home-x-foo"
    pdir.mkdir(parents=True)
    (pdir / "abc.jsonl").write_text("{}\n")
    assert claude_slug.has_transcript("/home/x/foo") is True


def test_has_transcript_false_missing_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert claude_slug.has_transcript("/home/x/foo") is False


def test_has_transcript_false_empty_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "projects" / "-home-x-foo").mkdir(parents=True)
    assert claude_slug.has_transcript("/home/x/foo") is False


def test_has_transcript_ignores_non_jsonl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    pdir = tmp_path / "projects" / "-home-x-foo"
    pdir.mkdir(parents=True)
    (pdir / "readme.txt").write_text("")
    assert claude_slug.has_transcript("/home/x/foo") is False
