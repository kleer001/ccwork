"""Tests for core/settings.py"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomlkit

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


def test_to_xterm_args_selection_writes_primary_and_clipboard() -> None:
    """Drag-select must populate both PRIMARY (for middle-click paste) and
    CLIPBOARD (so Ctrl+V in another app pastes what was highlighted).
    xterm's default `select-end(SELECT, CUT_BUFFER0)` only fills PRIMARY."""
    args = S.XtermSettings().to_xterm_args()
    xrm_values = [args[i + 1] for i, v in enumerate(args[:-1]) if v == "-xrm"]
    vt100 = next((v for v in xrm_values if v.startswith("XTerm*VT100.translations")), "")
    assert "<Btn1Up>" in vt100
    assert "select-end(PRIMARY, CLIPBOARD" in vt100


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
    assert "<Btn1Down>" in body and "<Btn1Motion>" in body and "<Btn1Up>" in body
    assert "MoveThumb" in body and "NotifyThumb" in body
    assert "Btn2" not in body


def test_to_xterm_args_enables_allow_font_ops() -> None:
    args = S.XtermSettings().to_xterm_args()
    xrm_values = [args[i + 1] for i, v in enumerate(args[:-1]) if v == "-xrm"]
    assert any("allowFontOps" in v and "true" in v for v in xrm_values), xrm_values


def test_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    s = S.load_settings(tmp_path / "nope.toml")
    assert s.xterm == S.XtermSettings()
    assert s.ui.layout == S.LayoutSettings()
    assert s.ui.animation == S.AnimationSettings()


def test_load_corrupt_toml_returns_defaults(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    p = tmp_path / "settings.toml"
    p.write_text("[xterm\nfont_size = oops")
    import logging
    with caplog.at_level(logging.WARNING):
        s = S.load_settings(p)
    assert s.xterm == S.XtermSettings()
    assert any("not valid TOML" in r.message for r in caplog.records)


def test_round_trip_preserves_values(tmp_path: Path) -> None:
    p = tmp_path / "s.toml"
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
    p = tmp_path / "s.toml"
    p.write_text(
        "version = 2\n"
        "\n"
        "[xterm]\n"
        "font_size = 12\n"
        "\n"
        "[future_feature]\n"
        'color_scheme = "solarized"\n'
    )
    loaded = S.load_settings(p)
    assert loaded.xterm.font_size == 12
    S.save_settings(loaded, p)
    saved = tomlkit.parse(p.read_text())
    assert saved.get("future_feature", {}).get("color_scheme") == "solarized"


def test_round_trip_preserves_user_comments(tmp_path: Path) -> None:
    """Hand-edited comments must survive a GUI-triggered save round-trip —
    this is the whole reason we picked tomlkit over tomli-w."""
    p = tmp_path / "s.toml"
    p.write_text(
        "# user's notes — keep these!\n"
        "version = 2\n"
        "\n"
        "[xterm]\n"
        "# I like a tiny font\n"
        "font_size = 9\n"
    )
    loaded = S.load_settings(p)
    assert loaded.xterm.font_size == 9
    S.save_settings(loaded, p)
    text = p.read_text()
    assert "user's notes" in text
    assert "tiny font" in text


def test_ui_settings_defaults() -> None:
    u = S.UISettings()
    assert u.sidebar_side == "left"
    assert u.sidebar_width >= 120
    assert u.restore_last_repo is True
    assert u.desktop_notifications is True
    assert u.auto_arrange_repos is False
    assert u.group_active_repos is True
    assert u.warn_on_ctrl_c is True


def test_ui_settings_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "s.toml"
    orig = S.Settings(ui=S.UISettings(
        sidebar_side="right", sidebar_width=310,
        restore_last_repo=False, desktop_notifications=False,
        auto_arrange_repos=True,
        group_active_repos=False,
        warn_on_ctrl_c=False,
    ))
    S.save_settings(orig, p)
    loaded = S.load_settings(p)
    assert loaded.ui.sidebar_side == "right"
    assert loaded.ui.sidebar_width == 310
    assert loaded.ui.restore_last_repo is False
    assert loaded.ui.desktop_notifications is False
    assert loaded.ui.auto_arrange_repos is True
    assert loaded.ui.group_active_repos is False
    assert loaded.ui.warn_on_ctrl_c is False


def test_ui_settings_invalid_side_falls_back_to_default(tmp_path: Path) -> None:
    p = tmp_path / "s.toml"
    p.write_text('[ui]\nsidebar_side = "top"\n')
    loaded = S.load_settings(p)
    assert loaded.ui.sidebar_side == "left"


def test_ui_settings_min_width_enforced_on_load(tmp_path: Path) -> None:
    p = tmp_path / "s.toml"
    p.write_text("[ui]\nsidebar_width = 30\n")
    loaded = S.load_settings(p)
    assert loaded.ui.sidebar_width >= 60


def test_ui_settings_max_width_enforced_on_load(tmp_path: Path) -> None:
    """Bound on load matches the dialog spinbox so a hand-edited overshoot
    doesn't silently get clamped (and persisted) the next time the user
    opens Preferences."""
    p = tmp_path / "s.toml"
    p.write_text("[ui]\nsidebar_width = 5000\n")
    loaded = S.load_settings(p)
    assert loaded.ui.sidebar_width <= 600


def test_write_default_settings_file_creates_once(tmp_path: Path) -> None:
    p = tmp_path / "s.toml"
    S.write_default_settings_file(p)
    assert p.exists()
    orig_mtime = p.stat().st_mtime
    import time
    time.sleep(0.01)
    S.write_default_settings_file(p)
    assert p.stat().st_mtime == orig_mtime


# ── Layout & animation knobs ──────────────────────────────────────────────


def test_layout_defaults_match_legacy_hardcodes() -> None:
    """Defaults must match the previous class-constants in RepoDelegate so
    nothing visually changes when no TOML is present."""
    L = S.LayoutSettings()
    assert L.row_height == 52
    assert L.padding_x == 10
    assert L.group_gap_h == 10
    assert L.glyph_w == 14
    assert L.glyph_gap == 4
    assert L.active_stripe_w == 3
    assert L.last_focused_stripe_w == 2


def test_animation_defaults_match_legacy_hardcodes() -> None:
    A = S.AnimationSettings()
    assert A.spinner_interval_ms == 100
    assert A.arrange_step_min_ms == 80
    assert A.arrange_step_max_ms == 220
    assert A.sidebar_quiet_ms == 800
    assert A.reorder_debounce_ms == 2000
    assert A.splitter_debounce_ms == 300


def test_layout_and_animation_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "s.toml"
    orig = S.Settings(ui=S.UISettings(
        layout=S.LayoutSettings(row_height=70, glyph_w=18),
        animation=S.AnimationSettings(spinner_interval_ms=50, arrange_step_max_ms=400),
    ))
    S.save_settings(orig, p)
    loaded = S.load_settings(p)
    assert loaded.ui.layout.row_height == 70
    assert loaded.ui.layout.glyph_w == 18
    # Unspecified knobs in the same section should still load from defaults.
    assert loaded.ui.layout.padding_x == S.LayoutSettings().padding_x
    assert loaded.ui.animation.spinner_interval_ms == 50
    assert loaded.ui.animation.arrange_step_max_ms == 400


# ── JSON → TOML migration ─────────────────────────────────────────────────


def test_migration_reads_legacy_json(tmp_path: Path) -> None:
    """Old settings.json found at default path → migrated transparently."""
    legacy = tmp_path / "settings.json"
    legacy.write_text(json.dumps({
        "version": 1,
        "xterm": {"font_size": 13, "scrollbar": "left"},
        "ui": {"sidebar_width": 280, "auto_arrange_repos": True},
        "last_focused_repo": "/some/path",
    }))
    toml_path = tmp_path / "settings.toml"
    loaded = S.load_settings(toml_path)
    assert loaded.xterm.font_size == 13
    assert loaded.xterm.scrollbar == "left"
    assert loaded.ui.sidebar_width == 280
    assert loaded.ui.auto_arrange_repos is True
    assert loaded.last_focused_repo == "/some/path"


def test_migration_writes_toml_and_archives_json(tmp_path: Path) -> None:
    legacy = tmp_path / "settings.json"
    legacy.write_text(json.dumps({"xterm": {"font_size": 11}}))
    toml_path = tmp_path / "settings.toml"
    S.load_settings(toml_path)
    assert toml_path.exists(), "migration must produce a TOML file"
    bak = legacy.with_suffix(".json.bak")
    assert bak.exists(), "original JSON must be archived as .json.bak"
    assert not legacy.exists(), "original JSON must no longer exist at .json"


def test_migration_is_idempotent(tmp_path: Path) -> None:
    """Second load reads the freshly-written TOML, not the .bak."""
    legacy = tmp_path / "settings.json"
    legacy.write_text(json.dumps({"xterm": {"font_size": 13}}))
    toml_path = tmp_path / "settings.toml"
    first = S.load_settings(toml_path)
    second = S.load_settings(toml_path)
    assert first.xterm.font_size == 13
    assert second.xterm.font_size == 13
    # And the .bak is not consumed again
    assert (legacy.with_suffix(".json.bak")).exists()


def test_no_legacy_no_toml_returns_defaults(tmp_path: Path) -> None:
    """If neither file exists, return defaults — don't create anything."""
    toml_path = tmp_path / "settings.toml"
    s = S.load_settings(toml_path)
    assert s.xterm == S.XtermSettings()
    assert not toml_path.exists()


# ── Window geometry ───────────────────────────────────────────────────────


def test_window_state_defaults() -> None:
    assert S.WindowState().geometry == ""
    assert S.Settings().window == S.WindowState()


def test_window_state_round_trip(tmp_path: Path) -> None:
    """The geometry blob is opaque base64 — settings.py never decodes it,
    just stores and retrieves byte-for-byte."""
    import base64
    blob = base64.b64encode(b"fake-Qt-saveGeometry-output").decode("ascii")
    p = tmp_path / "s.toml"
    orig = S.Settings(window=S.WindowState(geometry=blob))
    S.save_settings(orig, p)
    loaded = S.load_settings(p)
    assert loaded.window.geometry == blob


def test_window_state_survives_unknown_keys_and_comments(tmp_path: Path) -> None:
    """Hand-edited comments inside [window] must round-trip a GUI save —
    same _raw / _merge_into invariant as the other sections."""
    p = tmp_path / "s.toml"
    p.write_text(
        "version = 2\n"
        "\n"
        "[xterm]\n"
        "font_size = 11\n"
        "\n"
        "# I dragged the window onto monitor 2 and want it to stay\n"
        "[window]\n"
        '# this blob was captured 2026-05-13\n'
        'geometry = "AAAA-fake-blob"\n'
    )
    loaded = S.load_settings(p)
    assert loaded.window.geometry == "AAAA-fake-blob"
    S.save_settings(loaded, p)
    text = p.read_text()
    assert "monitor 2" in text
    assert "captured 2026-05-13" in text
    assert "AAAA-fake-blob" in text


def test_corrupt_window_geometry_loads_clean(tmp_path: Path) -> None:
    """settings.py doesn't validate the blob — base64-decode happens in
    MainWindow._restore_window_geometry. Load must succeed with whatever
    string the file contains; the decode/restore failure is handled later
    via a WARNING log."""
    p = tmp_path / "s.toml"
    p.write_text(
        "version = 2\n"
        "\n"
        "[window]\n"
        'geometry = "not-valid-base64!!!"\n'
    )
    loaded = S.load_settings(p)
    assert loaded.window.geometry == "not-valid-base64!!!"
