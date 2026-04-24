"""Tests for core/settings.py"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core import settings as S


def test_defaults_are_sensible() -> None:
    x = S.XtermSettings()
    assert x.font_family == "Monospace"
    assert x.scrollback >= 20000
    assert x.scrollbar in ("right", "left", "none")


def test_to_xterm_args_right_scrollbar() -> None:
    x = S.XtermSettings(font_size=12, scrollback=5000, scrollbar="right")
    args = x.to_xterm_args()
    assert "-fs" in args and args[args.index("-fs") + 1] == "12"
    assert "-sl" in args and args[args.index("-sl") + 1] == "5000"
    assert "-sb" in args
    assert "-rightbar" in args
    assert "+sb" not in args


def test_to_xterm_args_none_scrollbar() -> None:
    args = S.XtermSettings(scrollbar="none").to_xterm_args()
    assert "+sb" in args
    assert "-rightbar" not in args and "-leftbar" not in args


def test_to_xterm_args_includes_wheel_bindings() -> None:
    args = S.XtermSettings().to_xterm_args()
    xrm_idx = args.index("-xrm")
    assert "scroll-back" in args[xrm_idx + 1]
    assert "scroll-forw" in args[xrm_idx + 1]


def test_to_xterm_args_extras_appended_last() -> None:
    extras = ["-xrm", "XTerm*cursorBlink: true"]
    args = S.XtermSettings(extra_args=extras).to_xterm_args()
    assert args[-2:] == extras


def test_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    s = S.load_settings(tmp_path / "nope.json")
    assert s.xterm == S.XtermSettings()


def test_load_corrupt_json_returns_defaults(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    p = tmp_path / "settings.json"
    p.write_text("{not json")
    import logging
    with caplog.at_level(logging.WARNING):
        s = S.load_settings(p)
    assert s.xterm == S.XtermSettings()
    assert any("not valid JSON" in r.message for r in caplog.records)


def test_round_trip_preserves_values(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    orig = S.Settings(
        xterm=S.XtermSettings(font_size=14, scrollback=999, scrollbar="left", bg="#000", fg="#fff")
    )
    S.save_settings(orig, p)
    loaded = S.load_settings(p)
    assert loaded.xterm.font_size == 14
    assert loaded.xterm.scrollback == 999
    assert loaded.xterm.scrollbar == "left"
    assert loaded.xterm.bg == "#000"


def test_round_trip_preserves_unknown_keys(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    p.write_text(json.dumps({
        "version": 1,
        "xterm": {"font_size": 12},
        "future_feature": {"color_scheme": "solarized"},
    }))
    loaded = S.load_settings(p)
    assert loaded.xterm.font_size == 12
    S.save_settings(loaded, p)
    saved = json.loads(p.read_text())
    assert saved.get("future_feature", {}).get("color_scheme") == "solarized"


def test_write_default_settings_file_creates_once(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    S.write_default_settings_file(p)
    assert p.exists()
    orig_mtime = p.stat().st_mtime
    # Second call must not overwrite an existing file.
    import time
    time.sleep(0.01)
    S.write_default_settings_file(p)
    assert p.stat().st_mtime == orig_mtime
