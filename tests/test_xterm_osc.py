"""Tests for OSC sequence generation + PTY discovery."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core import xterm_osc
from src.core.settings import XtermSettings


def test_osc_format() -> None:
    s = xterm_osc.osc(11, "#112233")
    assert s == "\x1b]11;#112233\x07"


def test_apply_live_unknown_pid_returns_full_list() -> None:
    # PID 1 exists but its child ≠ an xterm shell — find_child_pty may
    # succeed or fail; either way, apply_live should not raise.
    result = xterm_osc.apply_live(999_999, XtermSettings())
    # Unknown PID: children lookup fails → everything unapplied.
    assert set(result) >= {"bg", "fg", "font_family", "font_size", "scrollback", "scrollbar"}


def test_find_child_pty_returns_none_for_unknown(tmp_path: Path) -> None:
    assert xterm_osc.find_child_pty(999_999) is None


def test_write_to_pty_fails_gracefully_on_missing(tmp_path: Path) -> None:
    assert xterm_osc.write_to_pty(tmp_path / "nope", "\x1b]11;#000\x07") is False


def test_write_to_pty_writes_to_real_file(tmp_path: Path) -> None:
    """Using a regular file is a stand-in for /dev/pts/N — proves the write
    path delivers the exact bytes we build."""
    p = tmp_path / "sink"
    p.touch()
    assert xterm_osc.write_to_pty(p, "hello") is True
    assert p.read_bytes() == b"hello"


def test_apply_live_returns_restart_only_fields_when_pty_reachable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force find_child_pty + write_to_pty to succeed with a fake PTY."""
    sink = tmp_path / "sink"
    sink.touch()
    monkeypatch.setattr(xterm_osc, "find_child_pty", lambda pid: sink)
    unapplied = xterm_osc.apply_live(1234, XtermSettings(bg="#112233", fg="#aabbcc"))
    # Colors + font face applied; startup-only knobs remain.
    assert "bg" not in unapplied
    assert "fg" not in unapplied
    assert "font_family" not in unapplied
    assert "font_size" in unapplied
    assert "scrollback" in unapplied
    assert "scrollbar" in unapplied
    # And the bytes actually landed.
    data = sink.read_bytes().decode("utf-8")
    assert "\x1b]10;#aabbcc\x07" in data
    assert "\x1b]11;#112233\x07" in data
    assert "\x1b]50;Monospace\x07" in data
