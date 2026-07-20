"""Badge presentation data for the repo sidebar.

Single source of truth for every glyph, color, label, and animation frame
the sidebar paints. Both `RepoListModel` (tooltips) and `RepoDelegate`
(badge painting) read from here, so the values live in one module that
neither imports — keeping the model / delegate / widget split free of
cycles.

Values come from built-in defaults, optionally overridden by
`~/.config/ccwork/badges.toml` (respects `$XDG_CONFIG_HOME`). The file is
read once, at import. Any key you omit keeps its default, so a partial file
is fine and a missing file uses the defaults verbatim. Malformed values
fail loudly at startup rather than silently falling back to a default.

Example `badges.toml`::

    # Colors accept four notations — pick whichever per value:
    #   "#268bd2"            hex (also #rgb, #rrggbbaa)
    #   "rgb(38, 139, 210)"  components 0–255
    #   "hsv(205, 82, 82)"   Qt-native: hue 0–360, saturation 0–255, value 0–255
    #   "steelblue"          any SVG/X11 color name
    spinner_color   = "rgb(38, 139, 210)"
    subagent_color  = "#2aa198"
    ambient_color   = "hsv(194, 63, 117)"
    last_focused    = "slateblue"
    session_glyph   = "⠿"
    subagent_frames = ["✲", "✵", "✷", "✱", "❂", "✹", "✺", "✸", "❉", "❊", "❋"]

    [statuses.done]
    color = "#859900"
    glyph = "✓"
    label = "Claude finished a turn"

    [statuses.attention]
    color = "#dc322f"
    glyph = "!"
    label = "Claude needs input"

The status *value* strings (`STATUS_DONE`, `STATUS_ATTENTION`) are protocol
identifiers the event system keys on and are not themable; the color /
glyph / label attached to each are.
"""

from __future__ import annotations

import copy
import os
import zlib
from dataclasses import dataclass
from pathlib import Path

import tomlkit
from PySide6.QtGui import QColor


@dataclass(frozen=True)
class StatusDefinition:
    """Single source of truth for a Claude alert: tooltip label + badge paint."""
    value: str
    label: str
    color: QColor
    glyph: str


# Status *value* strings — protocol identifiers the event system keys on.
# Not themable (the color / glyph / label attached to each are).
STATUS_DONE      = "done"
STATUS_ATTENTION = "attention"

# Tooltip text that isn't tied to a glyph/color knob — kept in code.
WORKING_LABEL = "Claude is working…"
LAST_FOCUSED_LABEL = "Last focused"
SUBAGENTS_LABEL = "Subagents running"
SESSION_ACTIVE_LABEL = "Claude session active"
TERMINAL_ONLY_LABEL = "Terminal open (no Claude session)"

# Built-in defaults — the look when no badges.toml is present. Colors are
# the canonical solarized hex; the loader also accepts rgb(), hsv(), and
# SVG names in the override file.
#   done   = solarized green (calmer), attention = solarized red (urgent)
#   spinner = solarized blue, subagent = solarized cyan (live parallel
#   work), ambient = solarized base01 (quiet presence), last-focused =
#   solarized violet.
# subagent_frames are concentric asterisk-stars (all center-aligned, similar
# size) ordered light→heavy→light, so the twinkle blooms and contracts as a
# smooth pulse without the glyph jittering off-center — the eye reads "a
# subagent is doing work". Paints one slot inboard of the main-turn spinner
# and advances at a third of its rate (see SUBAGENT_SLOWDOWN in
# repo_delegate). session_glyph ⠿ (dense braille) marks a live Claude
# session; a bare bash terminal gets no badge. spinner_variants: five
# braille cycles; each repo gets one deterministically (see spinner_for_id).
_DEFAULTS: dict = {
    "spinner_color": "#268bd2",
    "subagent_color": "#2aa198",
    "ambient_color": "#586e75",
    "last_focused": "#6c71c4",
    "session_glyph": "⠿",
    "subagent_frames": ["✲", "✵", "✷", "✱", "❂", "✹", "✺", "✸", "❉", "❊", "❋", "❊", "❉", "✸", "✺", "✹", "❂", "✱", "✷", "✵"],
    "spinner_variants": [
        ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
        ["⠋", "⠙", "⠚", "⠞", "⠖", "⠦", "⠴", "⠲", "⠳", "⠓"],
        ["⠄", "⠆", "⠇", "⠦", "⠴", "⠼", "⠸", "⠰", "⠠", "⠰", "⠸", "⠼", "⠴", "⠦", "⠇", "⠆"],
        ["⣀", "⣄", "⣤", "⣦", "⣶", "⣷", "⣿", "⣷", "⣶", "⣦", "⣤", "⣄"],
        ["⠄", "⠆", "⠇", "⠋", "⠙", "⠸", "⠰", "⠠", "⠰", "⠸", "⠙", "⠋", "⠇", "⠆"],
    ],
    "statuses": {
        "done": {"color": "#859900", "glyph": "✓", "label": "Claude finished a turn"},
        "attention": {"color": "#dc322f", "glyph": "!", "label": "Claude needs input"},
    },
}

_TOP_KEYS = frozenset(_DEFAULTS)
_STATUS_NAMES = frozenset({STATUS_DONE, STATUS_ATTENTION})
_STATUS_FIELDS = frozenset({"color", "glyph", "label"})


@dataclass(frozen=True)
class BadgeTheme:
    """Resolved badge theme: defaults overlaid with the user's badges.toml."""
    spinner_color: QColor
    subagent_color: QColor
    ambient_color: QColor
    last_focused: QColor
    session_glyph: str
    subagent_frames: tuple[str, ...]
    spinner_variants: tuple[tuple[str, ...], ...]
    status_done: StatusDefinition
    status_attention: StatusDefinition


def _badges_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "ccwork" / "badges.toml"


def _reject_unknown(table: dict, allowed: frozenset, *, where: str) -> None:
    for key in table:
        if key not in allowed:
            raise ValueError(
                f"badges.toml: unknown key {key!r} in {where} "
                f"(expected one of: {', '.join(sorted(allowed))})"
            )


def _read_overrides(path: Path | None) -> dict:
    """Parse the override file into a plain dict. {} when the file is absent.

    Raises on invalid TOML or unknown keys — a typo'd key would otherwise
    silently do nothing, which is exactly the kind of quiet fallback the
    project forbids.
    """
    p = path if path is not None else _badges_path()
    if not p.exists():
        return {}
    try:
        data = dict(tomlkit.parse(p.read_text() or ""))
    except Exception as e:  # tomlkit raises various ParseError subclasses
        raise ValueError(f"badges.toml ({p}): not valid TOML: {e}") from e
    _reject_unknown(data, _TOP_KEYS, where="the top level")
    statuses = data.get("statuses")
    if statuses is not None:
        if not isinstance(statuses, dict):
            raise ValueError("badges.toml: [statuses] must be a table")
        _reject_unknown(statuses, _STATUS_NAMES, where="[statuses]")
        for name, sub in statuses.items():
            if not isinstance(sub, dict):
                raise ValueError(f"badges.toml: [statuses.{name}] must be a table")
            _reject_unknown(sub, _STATUS_FIELDS, where=f"[statuses.{name}]")
    return data


def _merge_defaults(overrides: dict) -> dict:
    """Overlay `overrides` onto `_DEFAULTS`: flat keys whole, statuses field-by-field.

    `_read_overrides` already rejected unknown keys, so every flat key here is
    a known `_DEFAULTS` knob; `statuses` is the one nested table and is merged
    field-by-field below.
    """
    cfg = copy.deepcopy(_DEFAULTS)
    for key, value in overrides.items():
        if key != "statuses":
            cfg[key] = value
    override_statuses = overrides.get("statuses", {})
    for name in _STATUS_NAMES:
        sub = override_statuses.get(name, {})
        for field_name in _STATUS_FIELDS:
            if field_name in sub:
                cfg["statuses"][name][field_name] = sub[field_name]
    return cfg


def _color_components(s: str, *, where: str, count: int) -> list[int]:
    inner = s[s.index("(") + 1:-1]
    parts = [p.strip() for p in inner.split(",")]
    if len(parts) != count:
        raise ValueError(
            f"badges.toml: {where}: expected {count} comma-separated numbers, got {s!r}"
        )
    try:
        return [int(p) for p in parts]
    except ValueError:
        raise ValueError(
            f"badges.toml: {where}: components must be integers, got {s!r}"
        ) from None


def _parse_color(value, *, where: str) -> QColor:
    """Parse one color value. Accepts #hex, rgb(r,g,b), hsv(h,s,v), or an
    SVG color name. Raises on anything unrecognized — no silent fallback."""
    if not isinstance(value, str):
        raise ValueError(f"badges.toml: {where} must be a color string, got {value!r}")
    s = str(value).strip()
    low = s.lower()
    if low.startswith("rgb(") and s.endswith(")"):
        nums = _color_components(s, where=where, count=3)
        if any(not 0 <= n <= 255 for n in nums):
            raise ValueError(
                f"badges.toml: {where}: rgb() components must be 0–255, got {value!r}"
            )
        return QColor.fromRgb(*nums)
    if low.startswith("hsv(") and s.endswith(")"):
        h, sat, val = _color_components(s, where=where, count=3)
        if not 0 <= h <= 360:
            raise ValueError(f"badges.toml: {where}: hsv() hue must be 0–360, got {value!r}")
        if not (0 <= sat <= 255 and 0 <= val <= 255):
            raise ValueError(
                f"badges.toml: {where}: hsv() saturation/value must be 0–255, got {value!r}"
            )
        # Qt-native HSV (hue 0–359, saturation/value 0–255). Normalize to RGB
        # spec because QColor.__eq__ compares spec + values, so an Hsv-spec
        # color would never compare equal to an identical hex one.
        return QColor.fromHsv(h % 360, sat, val).toRgb()
    color = QColor(s)  # #hex forms and SVG/X11 color names
    if not color.isValid():
        raise ValueError(
            f"badges.toml: {where}: unrecognized color {value!r} — use #hex, "
            f"rgb(r,g,b), hsv(h,s,v), or an SVG color name"
        )
    return color


def _require_text(value, *, where: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"badges.toml: {where} must be a string, got {value!r}")
    return str(value)


def _require_glyph(value, *, where: str) -> str:
    text = _require_text(value, where=where)
    if text == "":
        raise ValueError(f"badges.toml: {where} must be a non-empty string")
    return text


def _require_frames(value, *, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) == 0:
        raise ValueError(f"badges.toml: {where} must be a non-empty array of strings")
    return tuple(_require_glyph(v, where=f"{where}[{i}]") for i, v in enumerate(value))


def _require_variants(value, *, where: str) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list) or len(value) == 0:
        raise ValueError(f"badges.toml: {where} must be a non-empty array of arrays")
    return tuple(_require_frames(row, where=f"{where}[{i}]") for i, row in enumerate(value))


def _status(cfg: dict, name: str) -> StatusDefinition:
    sub = cfg["statuses"][name]
    return StatusDefinition(
        value=name,
        label=_require_text(sub["label"], where=f"statuses.{name}.label"),
        color=_parse_color(sub["color"], where=f"statuses.{name}.color"),
        glyph=_require_glyph(sub["glyph"], where=f"statuses.{name}.glyph"),
    )


def load_badge_theme(path: Path | None = None) -> BadgeTheme:
    """Resolve the badge theme: built-in defaults overlaid with `path`
    (default `~/.config/ccwork/badges.toml`). Validates every value and
    raises `ValueError` on anything malformed."""
    cfg = _merge_defaults(_read_overrides(path))
    return BadgeTheme(
        spinner_color=_parse_color(cfg["spinner_color"], where="spinner_color"),
        subagent_color=_parse_color(cfg["subagent_color"], where="subagent_color"),
        ambient_color=_parse_color(cfg["ambient_color"], where="ambient_color"),
        last_focused=_parse_color(cfg["last_focused"], where="last_focused"),
        session_glyph=_require_glyph(cfg["session_glyph"], where="session_glyph"),
        subagent_frames=_require_frames(cfg["subagent_frames"], where="subagent_frames"),
        spinner_variants=_require_variants(cfg["spinner_variants"], where="spinner_variants"),
        status_done=_status(cfg, STATUS_DONE),
        status_attention=_status(cfg, STATUS_ATTENTION),
    )


# ── Resolve once at import, then expose the values as module constants the
#    paint / tooltip code reads by name. ──
_THEME = load_badge_theme()

SPINNER_COLOR = _THEME.spinner_color
SUBAGENT_COLOR = _THEME.subagent_color
AMBIENT_COLOR = _THEME.ambient_color
LAST_FOCUSED_BASE = _THEME.last_focused
SESSION_ACTIVE_GLYPH = _THEME.session_glyph
SUBAGENT_FRAMES = _THEME.subagent_frames
SPINNER_VARIANTS = _THEME.spinner_variants

STATUS_DONE_DEF = _THEME.status_done
STATUS_ATTENTION_DEF = _THEME.status_attention
_ALL_STATUSES = (STATUS_DONE_DEF, STATUS_ATTENTION_DEF)

# Lookups keyed by status value. The right-edge badge column is reserved for
# genuine Claude alerts (working / done / attention); the last-focused
# bookmark paints a left-edge stripe in a different code path and is NOT in
# these dicts.
STATUS_LABELS = {s.value: s.label for s in _ALL_STATUSES}
STATUS_COLORS = {s.value: s.color for s in _ALL_STATUSES}
STATUS_GLYPHS = {s.value: s.glyph for s in _ALL_STATUSES}


def spinner_for_id(repo_id: str) -> tuple[str, ...]:
    """Pick a stable spinner variant for `repo_id`.

    crc32 (zlib stdlib) is used instead of Python's built-in `hash` because
    the latter is salted per-process — the variant would change on every
    launch, which would feel like a bug.
    """
    return SPINNER_VARIANTS[zlib.crc32(repo_id.encode("utf-8")) % len(SPINNER_VARIANTS)]
