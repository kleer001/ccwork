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


def test_to_xterm_args_rebinds_scrollbar_btn1_to_drag() -> None:
    """Xaw's default Btn1-on-scrollbar is line-down, not thumb-drag — which
    confuses every user. We override it to behave like a normal scrollbar.
    Scoped to the `scrollbar` widget so terminal-area selection (Btn1) and
    paste-on-middle-click (Btn2) stay at xterm defaults."""
    args = S.XtermSettings().to_xterm_args()
    xrm_values = [args[i + 1] for i, v in enumerate(args[:-1]) if v == "-xrm"]
    sb_overrides = [v for v in xrm_values if v.startswith("XTerm*scrollbar.translations")]
    assert sb_overrides, "scrollbar Btn1 rebind missing"
    body = sb_overrides[0]
    # Must rebind Btn1 specifically, and use proportional thumb actions.
    assert "<Btn1Down>" in body and "<Btn1Motion>" in body and "<Btn1Up>" in body
    assert "MoveThumb" in body and "NotifyThumb" in body
    # Must NOT mention Btn2 — that would step on paste in the VT100 area
    # if a user mistakenly broadens the resource.
    assert "Btn2" not in body


def test_to_xterm_args_enables_allow_font_ops() -> None:
    """OSC 50 font-change requires allowFontOps=true (xterm default is false),
    so the live-apply path in the GUI is dead without this flag."""
    args = S.XtermSettings().to_xterm_args()
    # Scan every -xrm pair for the allowFontOps declaration.
    xrm_values = [args[i + 1] for i, v in enumerate(args[:-1]) if v == "-xrm"]
    assert any("allowFontOps" in v and "true" in v for v in xrm_values), xrm_values


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


def test_ui_settings_defaults() -> None:
    u = S.UISettings()
    assert u.sidebar_side == "left"
    assert u.sidebar_width >= 120
    assert u.restore_last_repo is True
    assert u.desktop_notifications is True
    assert u.auto_arrange_repos is False
    assert u.group_active_repos is True


def test_ui_settings_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    orig = S.Settings(ui=S.UISettings(
        sidebar_side="right", sidebar_width=310,
        restore_last_repo=False, desktop_notifications=False,
        auto_arrange_repos=True,
        group_active_repos=False,
    ))
    S.save_settings(orig, p)
    loaded = S.load_settings(p)
    assert loaded.ui.sidebar_side == "right"
    assert loaded.ui.sidebar_width == 310
    assert loaded.ui.restore_last_repo is False
    assert loaded.ui.desktop_notifications is False
    assert loaded.ui.auto_arrange_repos is True
    assert loaded.ui.group_active_repos is False


def test_ui_settings_invalid_side_falls_back_to_default(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"ui": {"sidebar_side": "top"}}))
    loaded = S.load_settings(p)
    assert loaded.ui.sidebar_side == "left"


def test_ui_settings_min_width_enforced_on_load(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"ui": {"sidebar_width": 30}}))
    loaded = S.load_settings(p)
    assert loaded.ui.sidebar_width >= 60


def test_ui_settings_max_width_enforced_on_load(tmp_path: Path) -> None:
    """Bound on load matches the dialog spinbox so a hand-edited overshoot
    doesn't silently get clamped (and persisted) the next time the user
    opens Preferences."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"ui": {"sidebar_width": 5000}}))
    loaded = S.load_settings(p)
    assert loaded.ui.sidebar_width <= 600


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
