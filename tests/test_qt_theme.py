"""Tests for qt_theme palette derivation and application."""

from __future__ import annotations

import os

import pytest

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from src.core.settings import Settings, XtermSettings
from src.ui import qt_theme


def _hex(color: QColor) -> str:
    return color.name(QColor.HexRgb).lower()


def test_palette_window_matches_bg(qapp: QApplication) -> None:
    pal = qt_theme.build_palette(XtermSettings(bg="#002b36", fg="#93a1a1"))
    assert _hex(pal.color(QPalette.Window)) == "#002b36"
    assert _hex(pal.color(QPalette.WindowText)) == "#93a1a1"
    assert _hex(pal.color(QPalette.Text)) == "#93a1a1"
    assert _hex(pal.color(QPalette.ButtonText)) == "#93a1a1"


def test_dark_bg_produces_lighter_button(qapp: QApplication) -> None:
    pal = qt_theme.build_palette(XtermSettings(bg="#1e1e1e", fg="#d0d0d0"))
    window = pal.color(QPalette.Window).lightness()
    button = pal.color(QPalette.Button).lightness()
    assert button > window, (button, window)


def test_light_bg_produces_darker_button(qapp: QApplication) -> None:
    pal = qt_theme.build_palette(XtermSettings(bg="#fdf6e3", fg="#586e75"))
    window = pal.color(QPalette.Window).lightness()
    button = pal.color(QPalette.Button).lightness()
    assert button < window, (button, window)


def test_highlight_contrasts_highlighted_text(qapp: QApplication) -> None:
    pal = qt_theme.build_palette(XtermSettings(bg="#282a36", fg="#f8f8f2"))
    diff = abs(
        pal.color(QPalette.Highlight).lightness()
        - pal.color(QPalette.HighlightedText).lightness()
    )
    assert diff > 100, diff


def test_disabled_text_is_faded(qapp: QApplication) -> None:
    pal = qt_theme.build_palette(XtermSettings(bg="#1e1e1e", fg="#d0d0d0"))
    active = pal.color(QPalette.Active, QPalette.WindowText)
    disabled = pal.color(QPalette.Disabled, QPalette.WindowText)
    # The derivation sets alpha < 1 on disabled text roles.
    assert disabled.alphaF() < active.alphaF()


def test_placeholder_is_faded_foreground(qapp: QApplication) -> None:
    pal = qt_theme.build_palette(XtermSettings(bg="#1e1e1e", fg="#d0d0d0"))
    placeholder = pal.color(QPalette.PlaceholderText)
    assert placeholder.alphaF() < 1.0
    # Same hue as fg, just less opaque.
    assert _hex(QColor(placeholder.red(), placeholder.green(), placeholder.blue())) == "#d0d0d0"


def test_apply_theme_sets_fusion_and_palette(qapp: QApplication) -> None:
    s = Settings(xterm=XtermSettings(bg="#002b36", fg="#93a1a1"))
    qt_theme.apply_theme(qapp, s)
    # Palette lands on the app.
    assert _hex(qapp.palette().color(QPalette.Window)) == "#002b36"
    # Clearing the QSS reveals the base style under QStyleSheetStyle.
    qapp.setStyleSheet("")
    assert qapp.style().objectName().lower() == "fusion"
    # Restore so downstream tests aren't surprised by a cleared QSS.
    qapp.setStyleSheet(qt_theme.build_stylesheet(s.xterm))


def test_stylesheet_mentions_scrollbar_and_menu(qapp: QApplication) -> None:
    qss = qt_theme.build_stylesheet(XtermSettings())
    assert "QScrollBar" in qss
    assert "QMenu::separator" in qss
