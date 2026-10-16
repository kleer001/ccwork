"""Tests for the config-driven badge theme loader (src/ui/badge_theme.py).

Covers: the built-in defaults reproduce the historical solarized palette;
all four color notations parse; partial overrides keep the untouched
defaults; malformed / unknown / bad-type values fail loudly rather than
silently falling back.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QColor

from src.ui.badge_theme import (
    STATUS_ANSWER,
    STATUS_ATTENTION,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_USAGE_LIMIT,
    load_badge_theme,
)


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "badges.toml"
    p.write_text(text)
    return p


def test_status_values_are_stable_protocol_ids() -> None:
    """The status value strings are protocol identifiers, not theme data."""
    assert STATUS_DONE == "done"
    assert STATUS_ATTENTION == "attention"


def test_defaults_reproduce_solarized_palette(tmp_path: Path) -> None:
    """A missing badges.toml yields exactly the built-in palette."""
    t = load_badge_theme(tmp_path / "absent.toml")
    assert t.spinner_color == QColor(38, 139, 210)
    assert t.subagent_color == QColor(42, 161, 152)
    assert t.ambient_color == QColor(88, 110, 117)
    assert t.last_focused == QColor(108, 113, 196)
    assert t.statuses[STATUS_DONE].color == QColor(133, 153, 0)
    assert t.statuses[STATUS_DONE].glyph == "✓"
    assert t.statuses[STATUS_DONE].label == "Done"
    assert t.statuses[STATUS_DONE].value == STATUS_DONE
    assert t.statuses[STATUS_ATTENTION].color == QColor(220, 50, 47)
    assert t.statuses[STATUS_ATTENTION].value == STATUS_ATTENTION
    assert t.session_glyph == "⠿"
    assert t.subagent_frames == (
        "✲", "✵", "✷", "✱", "❂", "✹", "✺", "✸", "❉", "❊", "❋",
        "❊", "❉", "✸", "✺", "✹", "❂", "✱", "✷", "✵",
    )
    assert len(t.spinner_variants) == 5
    assert all(isinstance(v, tuple) for v in t.spinner_variants)


@pytest.mark.parametrize("literal, expected", [
    ('"#268bd2"', QColor(38, 139, 210)),
    ('"rgb(38, 139, 210)"', QColor(38, 139, 210)),
    ('"RGB(1, 2, 3)"', QColor(1, 2, 3)),          # case-insensitive function name
    ('"hsv(0, 255, 255)"', QColor(255, 0, 0)),    # pure red (Qt-native s/v 0–255)
    ('"hsv(120, 255, 255)"', QColor(0, 255, 0)),  # pure green
    ('"steelblue"', QColor("steelblue")),         # SVG color name
])
def test_color_notations(tmp_path: Path, literal: str, expected: QColor) -> None:
    t = load_badge_theme(_write(tmp_path, f"spinner_color = {literal}\n"))
    assert t.spinner_color == expected


def test_partial_override_keeps_defaults(tmp_path: Path) -> None:
    """Omitted keys keep their default; a status sub-table merges field-by-field."""
    p = _write(tmp_path, 'spinner_color = "rgb(1, 2, 3)"\n[statuses.done]\ncolor = "lime"\n')
    t = load_badge_theme(p)
    assert t.spinner_color == QColor(1, 2, 3)          # overridden
    assert t.statuses[STATUS_DONE].color == QColor("lime")       # overridden field
    assert t.statuses[STATUS_DONE].glyph == "✓"                  # sibling field kept
    assert t.subagent_color == QColor(42, 161, 152)    # untouched key kept


@pytest.mark.parametrize("text, needle", [
    ('spinner_color = "notacolor"', "unrecognized color"),
    ('spinner_color = "rgb(300, 0, 0)"', "0–255"),
    ('ambient_color = "hsv(0, 300, 0)"', "0–255"),
    ('spiner_color = "#fff"', "unknown key"),                # typo'd top-level key
    ('[statuses.bogus]\ncolor = "#fff"', "unknown key"),     # unknown status name
    ('session_glyph = ""', "non-empty"),
    ('spinner_color = 123', "must be a color string"),
    ('subagent_frames = []', "non-empty array"),
])
def test_malformed_fails_loudly(tmp_path: Path, text: str, needle: str) -> None:
    with pytest.raises(ValueError, match=needle):
        load_badge_theme(_write(tmp_path, text))


def test_invalid_toml_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not valid TOML"):
        load_badge_theme(_write(tmp_path, "spinner_color = "))


def test_status_overrides_for_new_badges(tmp_path: Path) -> None:
    """The answer, error and usage-limit badges take the same per-field
    override as done and attention."""
    p = _write(tmp_path, (
        '[statuses.answer]\ncolor = "rgb(1, 2, 3)"\nglyph = "A"\nlabel = "Pick one"\n'
        '[statuses.error]\nlabel = "Broke"\n'
        '[statuses.usage_limit]\nglyph = "U"\n'
    ))
    t = load_badge_theme(p)
    assert t.statuses[STATUS_ANSWER].color == QColor(1, 2, 3)
    assert t.statuses[STATUS_ANSWER].glyph == "A"
    assert t.statuses[STATUS_ANSWER].label == "Pick one"
    assert t.statuses[STATUS_ERROR].label == "Broke"
    assert t.statuses[STATUS_ERROR].glyph == "✗"              # sibling kept
    assert t.statuses[STATUS_USAGE_LIMIT].glyph == "U"
    assert t.statuses[STATUS_USAGE_LIMIT].label == "Usage limit reached"


def test_defaults_for_new_badges(tmp_path: Path) -> None:
    t = load_badge_theme(tmp_path / "absent.toml")
    assert t.statuses[STATUS_ANSWER].label == "Needs an answer"
    assert t.statuses[STATUS_ERROR].label == "API error"
    assert t.statuses[STATUS_USAGE_LIMIT].label == "Usage limit reached"
    assert t.statuses[STATUS_ATTENTION].label == "Needs permission"


def test_compact_glyph_and_color_override(tmp_path: Path) -> None:
    t = load_badge_theme(_write(tmp_path, 'compact_glyph = "*"\ncompact_color = "#123456"\n'))
    assert t.compact_glyph == "*"
    assert t.compact_color == QColor(0x12, 0x34, 0x56)


def test_compact_glyph_default(tmp_path: Path) -> None:
    assert load_badge_theme(tmp_path / "absent.toml").compact_glyph == "◐"


def test_unknown_status_field_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown key"):
        load_badge_theme(_write(tmp_path, '[statuses.answer]\nicon = "x"\n'))
