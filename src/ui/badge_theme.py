"""Badge presentation data for the repo sidebar.

Single source of truth for every glyph, color, label, and animation frame
the sidebar paints. Both `RepoListModel` (tooltips) and `RepoDelegate`
(badge painting) read from here, so the values live in one module that
neither imports — keeping the model / delegate / widget split free of
cycles.

Colors are `QColor` from the solarized palette. The status *value* strings
(`STATUS_DONE`, `STATUS_ATTENTION`) are protocol identifiers the event
system keys on; the label / color / glyph attached to each are the
presentation layer.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from PySide6.QtGui import QColor


@dataclass(frozen=True)
class StatusDefinition:
    """Single source of truth for a Claude alert: tooltip label + badge paint."""
    value: str
    label: str
    color: QColor
    glyph: str


# Solarized-ish palette: red = needs attention (urgent), green = done (calmer).
STATUS_DONE_DEF = StatusDefinition(
    value="done",
    label="Claude finished a turn",
    color=QColor(133, 153, 0),
    glyph="✓",
)
STATUS_ATTENTION_DEF = StatusDefinition(
    value="attention",
    label="Claude needs input",
    color=QColor(220, 50, 47),
    glyph="!",
)

_ALL_STATUSES = (STATUS_DONE_DEF, STATUS_ATTENTION_DEF)

STATUS_DONE      = STATUS_DONE_DEF.value
STATUS_ATTENTION = STATUS_ATTENTION_DEF.value

STATUS_LABELS = {s.value: s.label for s in _ALL_STATUSES}
# Glyph + color lookups keyed by status value. The right-edge badge column
# is reserved for genuine Claude alerts (working / done / attention); the
# last-focused bookmark paints a left-edge stripe in a different code path
# and is NOT in these dicts.
STATUS_COLORS = {s.value: s.color for s in _ALL_STATUSES}
STATUS_GLYPHS = {s.value: s.glyph for s in _ALL_STATUSES}

WORKING_LABEL = "Claude is working…"
LAST_FOCUSED_LABEL = "Last focused"
# Twinkle-pulse animation painted in the badge column when Claude's main
# turn is idle (no working spinner, no attention dot) but at least one
# background subagent is still running. Frames step ·→✦→✶→❋→✶→✦ — a
# Claude-flower asterisk growing and shrinking — so the eye reads
# "background work in flight" rather than "placeholder". Cycles on the
# same spinner_frame counter as the braille spinner; the timer
# (_refresh_spinner_timer) is started whenever any row is working OR has
# bg_agents > 0.
BG_AGENT_FRAMES: tuple[str, ...] = ("·", "✦", "✶", "❋", "✶", "✦")
BG_AGENTS_LABEL = "Background agents running"
# Ambient terminal-state badges. Lowest priority — only painted when a row
# has a live terminal AND no higher-priority Claude alert is showing. These
# answer the at-a-glance question "is there a Claude session in this
# terminal, or am I at a bare shell prompt?" without competing with the
# active alert palette (red/green/blue/cyan).
#
#   SESSION_ACTIVE_GLYPH ⠿ — dense braille, "Claude is here, sitting idle"
#     (on-brand with the braille spinner family that runs during turns)
#   TERMINAL_ONLY_GLYPH  ▌ — left-half block, the universal text-cursor
#     shape; reads as "bare bash, no Claude"
SESSION_ACTIVE_GLYPH = "⠿"
SESSION_ACTIVE_LABEL = "Claude session active"
TERMINAL_ONLY_GLYPH = "▌"
TERMINAL_ONLY_LABEL = "Terminal open (no Claude session)"

# Badge-column colors.
# Muted blue for the working spinner — distinct from the red/green status
# dots so glance-state is unambiguous.
SPINNER_COLOR = QColor(38, 139, 210)  # solarized blue
# Solarized cyan — sits between the spinner's blue and STATUS_DONE green on
# the palette, so it reads as "live secondary work" without being
# confusable with either the main spinner or the done dot.
BG_AGENTS_COLOR = QColor(42, 161, 152)
# Solarized base01 — a low-contrast gray that reads as "ambient state"
# against both light and dark themes. Used for both the ⠿ session-active
# and ▌ terminal-only indicators so they sit as quiet background presence,
# never competing with the alert palette.
AMBIENT_COLOR = QColor(88, 110, 117)
# Base hue for the "last focused" left-edge stripe (solarized violet).
# Modulated per-theme by RepoDelegate._last_focused_stripe_color so it
# stays subtle.
LAST_FOCUSED_BASE = QColor(108, 113, 196)

# Five braille spinner variants. Each repo gets one deterministically
# (crc32 of repo.id mod len) so the sidebar feels lightly varied without
# being noisy — the same repo always animates the same way.
SPINNER_VARIANTS: tuple[tuple[str, ...], ...] = (
    ("⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"),                  # classic rotating
    ("⠋","⠙","⠚","⠞","⠖","⠦","⠴","⠲","⠳","⠓"),                  # rolling wave
    ("⠄","⠆","⠇","⠦","⠴","⠼","⠸","⠰","⠠","⠰","⠸","⠼","⠴","⠦","⠇","⠆"),  # bouncing trio
    ("⣀","⣄","⣤","⣦","⣶","⣷","⣿","⣷","⣶","⣦","⣤","⣄"),          # pulse fill
    ("⠄","⠆","⠇","⠋","⠙","⠸","⠰","⠠","⠰","⠸","⠙","⠋","⠇","⠆"),  # center bounce
)


def spinner_for_id(repo_id: str) -> tuple[str, ...]:
    """Pick a stable spinner variant for `repo_id`.

    crc32 (zlib stdlib) is used instead of Python's built-in `hash` because
    the latter is salted per-process — the variant would change on every
    launch, which would feel like a bug.
    """
    return SPINNER_VARIANTS[zlib.crc32(repo_id.encode("utf-8")) % len(SPINNER_VARIANTS)]
