"""Tests for the Preferences dialog — scheme list + scheme matching logic.

Full dialog interaction is covered by a smoke test that opens, picks a
scheme, saves, and reloads — verifying round-trip through settings.json.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.core.settings import Settings, UISettings, XtermSettings, load_settings
from src.ui import preferences_dialog as PD


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_three_dark_three_light_exactly() -> None:
    assert len(PD.DARK_SCHEMES) == 3
    assert len(PD.LIGHT_SCHEMES) == 3
    assert all(s.kind == "dark" for s in PD.DARK_SCHEMES)
    assert all(s.kind == "light" for s in PD.LIGHT_SCHEMES)
    assert PD.CUSTOM_SCHEME.kind == "custom"


def test_all_scheme_names_unique() -> None:
    names = [s.name for s in PD.COLOR_SCHEMES]
    assert len(names) == len(set(names))


def test_every_preset_has_valid_hex() -> None:
    import re
    pat = re.compile(r"^#[0-9a-fA-F]{6}$")
    for s in PD.DARK_SCHEMES + PD.LIGHT_SCHEMES:
        assert pat.match(s.bg), f"{s.name}: bad bg {s.bg}"
        assert pat.match(s.fg), f"{s.name}: bad fg {s.fg}"


def test_light_schemes_actually_light_and_dark_actually_dark() -> None:
    """Quick sanity check: dark schemes have dark bg (< 50%), light > 50%."""
    from PySide6.QtGui import QColor
    for s in PD.DARK_SCHEMES:
        assert QColor(s.bg).lightness() < 128, f"{s.name} bg not dark"
    for s in PD.LIGHT_SCHEMES:
        assert QColor(s.bg).lightness() > 128, f"{s.name} bg not light"


def test_dialog_populates_combo_with_separators(qapp: QApplication) -> None:
    dlg = PD.PreferencesDialog(Settings())
    # 3 dark + separator + 3 light + separator + Custom = 9 items
    assert dlg._scheme.count() == 9
    # First three entries are the dark schemes by name.
    assert [dlg._scheme.itemText(i) for i in range(3)] == [s.name for s in PD.DARK_SCHEMES]
    # Item index 3 is a separator (empty text).
    assert dlg._scheme.itemText(3) == ""
    # Then the light group.
    assert [dlg._scheme.itemText(i) for i in range(4, 7)] == [s.name for s in PD.LIGHT_SCHEMES]
    assert dlg._scheme.itemText(7) == ""
    assert dlg._scheme.itemText(8) == "Custom"


def test_dialog_scheme_opens_on_matching_name(qapp: QApplication) -> None:
    s = Settings(xterm=XtermSettings(bg="#282a36", fg="#f8f8f2"))  # Dracula
    dlg = PD.PreferencesDialog(s)
    assert dlg._scheme.currentText() == "Dracula"


def test_dialog_scheme_is_custom_when_colors_dont_match(qapp: QApplication) -> None:
    s = Settings(xterm=XtermSettings(bg="#123456", fg="#abcdef"))
    dlg = PD.PreferencesDialog(s)
    assert dlg._scheme.currentText() == "Custom"


def test_dialog_picking_scheme_updates_colors(qapp: QApplication) -> None:
    dlg = PD.PreferencesDialog(Settings())
    dlg._scheme.setCurrentText("Solarized Light")
    assert dlg._bg.value().lower() == "#fdf6e3"
    assert dlg._fg.value().lower() == "#586e75"


def test_dialog_picking_scheme_then_manual_override_flips_to_custom(qapp: QApplication) -> None:
    dlg = PD.PreferencesDialog(Settings())
    dlg._scheme.setCurrentText("Gruvbox Dark")
    assert dlg._scheme.currentText() == "Gruvbox Dark"
    dlg._bg.set_value("#123456")  # user picks a new bg
    assert dlg._scheme.currentText() == "Custom"


def test_dialog_picking_custom_does_not_overwrite_colors(qapp: QApplication) -> None:
    s = Settings(xterm=XtermSettings(bg="#123456", fg="#abcdef"))
    dlg = PD.PreferencesDialog(s)
    # Already Custom; picking it again must be a no-op.
    dlg._scheme.setCurrentText("Custom")
    assert dlg._bg.value().lower() == "#123456"
    assert dlg._fg.value().lower() == "#abcdef"


def test_dialog_round_trip_via_save(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp = tempfile.mkdtemp()
    try:
        monkeypatch.setenv("XDG_CONFIG_HOME", tmp)
        dlg = PD.PreferencesDialog(Settings())
        dlg._scheme.setCurrentText("Solarized Dark")
        dlg._font_size.setValue(11)
        dlg._scrollback.setValue(55_555)
        dlg._on_save()
        loaded = load_settings()
        assert loaded.xterm.bg.lower() == "#002b36"
        assert loaded.xterm.fg.lower() == "#93a1a1"
        assert loaded.xterm.font_size == 11
        assert loaded.xterm.scrollback == 55_555
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ui_tab_round_trip_via_save(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp = tempfile.mkdtemp()
    try:
        monkeypatch.setenv("XDG_CONFIG_HOME", tmp)
        # sidebar_width is no longer in the dialog — it's only set via
        # splitter drag — but the dialog must preserve it through save.
        dlg = PD.PreferencesDialog(Settings(ui=UISettings(sidebar_width=280)))
        dlg._sidebar_side.setCurrentText("right")
        dlg._restore_last.setChecked(False)
        dlg._desktop_notifs.setChecked(False)
        dlg._auto_arrange.setChecked(True)
        dlg._group_active.setChecked(False)
        dlg._on_save()
        loaded = load_settings()
        assert loaded.ui.sidebar_side == "right"
        assert loaded.ui.sidebar_width == 280
        assert loaded.ui.restore_last_repo is False
        assert loaded.ui.desktop_notifications is False
        assert loaded.ui.auto_arrange_repos is True
        assert loaded.ui.group_active_repos is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ui_tab_initialized_from_settings(qapp: QApplication) -> None:
    s = Settings(ui=UISettings(sidebar_side="right", sidebar_width=333,
                               restore_last_repo=False, desktop_notifications=False,
                               auto_arrange_repos=True, group_active_repos=False))
    dlg = PD.PreferencesDialog(s)
    assert dlg._sidebar_side.currentText() == "right"
    assert dlg._restore_last.isChecked() is False
    assert dlg._desktop_notifs.isChecked() is False
    assert dlg._auto_arrange.isChecked() is True
    assert dlg._group_active.isChecked() is False
