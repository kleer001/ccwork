"""STATUS_LAST_FOCUSED renders as a left-edge stripe, not a right-edge dot.

The bookmark used to share the alert column with done/attention, which
meant violet competed with red/green for the same eye-level. After the
move, the badge column is reserved for genuine Claude alerts.
"""

from __future__ import annotations

from src.ui.repo_sidebar import (
    STATUS_ATTENTION,
    STATUS_DONE,
    STATUS_LAST_FOCUSED,
    RepoDelegate,
)


def test_last_focused_not_in_right_edge_badge_dicts() -> None:
    """The right-edge dot/glyph dicts must not list LAST_FOCUSED — it
    paints elsewhere now."""
    assert STATUS_LAST_FOCUSED not in RepoDelegate.STATUS_COLORS
    assert STATUS_LAST_FOCUSED not in RepoDelegate.STATUS_GLYPHS
    # Real alerts still ride the badge column.
    assert STATUS_ATTENTION in RepoDelegate.STATUS_COLORS
    assert STATUS_DONE in RepoDelegate.STATUS_COLORS


def test_last_focused_stripe_color_is_subtle_per_theme() -> None:
    """The stripe pushes the base hue toward the row background — lighter
    on light themes, darker on dark themes — so it reads as ambient
    bookmark, not as a status alert."""
    from PySide6.QtGui import QColor, QPalette

    base = RepoDelegate.LAST_FOCUSED_BASE

    light = QPalette()
    light.setColor(QPalette.Base, QColor(255, 255, 255))
    light_color = RepoDelegate._last_focused_stripe_color(light)
    # Lighter than the base hue → moves toward the white bg.
    assert light_color.lightness() > base.lightness()

    dark = QPalette()
    dark.setColor(QPalette.Base, QColor(20, 20, 20))
    dark_color = RepoDelegate._last_focused_stripe_color(dark)
    # Darker than the base hue → moves toward the black bg.
    assert dark_color.lightness() < base.lightness()
