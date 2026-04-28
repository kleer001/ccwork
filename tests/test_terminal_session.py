"""Tests for terminal_session argv construction."""

from __future__ import annotations

import pytest
from src.core import terminal_session
from src.core.repo_store import Repo


def _split_on_dash_e(argv: list[str]) -> tuple[list[str], list[str]]:
    """Return (xterm_flags_before_-e, inner_cmd_after_-e)."""
    idx = argv.index("-e")
    return argv[:idx], argv[idx + 1 :]


def test_drops_into_interactive_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    spec = terminal_session.build_session(Repo(path="/fake/repo"))
    flags, inner = _split_on_dash_e(spec.argv)
    assert inner == ["/bin/bash", "-i"]
    assert "-fs" in flags  # settings flags are prepended before -e
    assert spec.env == {"CCWORK_GUI": "1"}
    assert spec.cwd == "/fake/repo"


def test_shell_fallback_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHELL", raising=False)
    spec = terminal_session.build_session(Repo(path="/fake/repo"))
    _, inner = _split_on_dash_e(spec.argv)
    # SHELL unset → fall back to bash if present, else /bin/sh.
    assert inner[1] == "-i"
    assert inner[0] in ("/bin/bash", "/bin/sh") or inner[0].endswith("/bash")


def test_settings_flags_are_applied() -> None:
    from src.core.settings import XtermSettings
    x = XtermSettings(font_size=8, scrollback=12345, scrollbar="none", jump_scroll=False)
    spec = terminal_session.build_session(Repo(path="/fake/repo"), xterm_settings=x)
    flags, _ = _split_on_dash_e(spec.argv)
    assert "-fs" in flags and flags[flags.index("-fs") + 1] == "8"
    assert "-sl" in flags and flags[flags.index("-sl") + 1] == "12345"
    assert "+sb" in flags
    assert "-j" not in flags


def test_gui_marker_toggleable() -> None:
    spec = terminal_session.build_session(Repo(path="/fake/repo"), gui_marker=False)
    assert spec.env == {}
