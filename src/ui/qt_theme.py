"""Derive a Qt application palette from the xterm color settings.

When the user picks "Dracula" for the terminal, we want the sidebar, menu
bar, title strip, Preferences dialog, etc. to wear the same colors — so
the GUI chrome doesn't clash with the embedded xterm.

We build a `QPalette` from `XtermSettings.bg` / `.fg`, derive intermediate
tones via `QColor.lighter()`/`.darker()`, and apply it to the
`QApplication`. A short QSS patch covers roles that `QPalette` can't theme
(menu separators, scrollbars, tooltip border).

We also force `setStyle("Fusion")`. Native platform styles (Breeze on KDE,
Adwaita on GNOME) frequently ignore palette overrides for Window / Base /
Button colors — Fusion honors the palette universally, which is exactly
what we want here.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from src.core.settings import Settings, XtermSettings

_DARK_ACCENT = "#268bd2"   # Solarized blue — readable on every bundled dark bg
_LIGHT_ACCENT = "#2aa198"  # Solarized cyan — readable on the bundled light bgs


def _tones(bg: QColor, fg: QColor) -> dict[str, QColor]:
    """Compute the derived tones used for Base/Button/Mid/etc.

    For dark bgs we go lighter for Base/Button (so input fields and buttons
    stand out against the window); for light bgs we go darker. Ratios picked
    to keep contrast above AA at every preset.
    """
    is_dark = bg.lightness() < 128

    def step(factor_dark: int, factor_light: int) -> QColor:
        return bg.lighter(factor_dark) if is_dark else bg.darker(factor_light)

    return {
        "window": QColor(bg),
        "base": step(110, 102),
        "alt_base": step(125, 106),
        "button": step(140, 108),
        "mid": step(160, 112),
        "midlight": step(135, 104),
        "dark": step(90, 120),      # "dark" role is BELOW button for shadow edges
        "shadow": step(70, 135),
        "tooltip_bg": step(150, 115),
        # Tonal selection: a quiet shade of the surface, not a hue accent.
        # Slightly lighter in dark mode, slightly darker in light mode.
        # Vivid color is reserved for `accent` (links, focus rings) where
        # the user's eye actually needs to be pulled.
        "highlight": step(130, 106),
        "accent": QColor(_DARK_ACCENT if is_dark else _LIGHT_ACCENT),
        "fg": QColor(fg),
    }


def _with_alpha(color: QColor, alpha: float) -> QColor:
    out = QColor(color)
    out.setAlphaF(alpha)
    return out


def build_palette(xt: XtermSettings) -> QPalette:
    """Return a QPalette mirroring the terminal bg/fg."""
    bg = QColor(xt.bg)
    fg = QColor(xt.fg)
    t = _tones(bg, fg)

    # Tonal highlight is close to bg lightness, so regular fg already
    # contrasts. No need to flip to white/black like a vivid highlight needs.
    highlighted_text = QColor(fg)
    bright_text = QColor("#ffffff") if bg.lightness() < 128 else QColor("#000000")

    pal = QPalette()
    for group in (QPalette.Active, QPalette.Inactive):
        pal.setColor(group, QPalette.Window, t["window"])
        pal.setColor(group, QPalette.WindowText, t["fg"])
        pal.setColor(group, QPalette.Base, t["base"])
        pal.setColor(group, QPalette.AlternateBase, t["alt_base"])
        pal.setColor(group, QPalette.Text, t["fg"])
        pal.setColor(group, QPalette.Button, t["button"])
        pal.setColor(group, QPalette.ButtonText, t["fg"])
        pal.setColor(group, QPalette.BrightText, bright_text)
        pal.setColor(group, QPalette.Mid, t["mid"])
        pal.setColor(group, QPalette.Midlight, t["midlight"])
        pal.setColor(group, QPalette.Dark, t["dark"])
        pal.setColor(group, QPalette.Shadow, t["shadow"])
        pal.setColor(group, QPalette.Highlight, t["highlight"])
        pal.setColor(group, QPalette.HighlightedText, highlighted_text)
        pal.setColor(group, QPalette.ToolTipBase, t["tooltip_bg"])
        pal.setColor(group, QPalette.ToolTipText, t["fg"])
        pal.setColor(group, QPalette.PlaceholderText, _with_alpha(t["fg"], 0.55))
        # Links + visited links use the saturated accent — that's where
        # vivid color earns its keep, not on selection backgrounds.
        pal.setColor(group, QPalette.Link, t["accent"])
        pal.setColor(group, QPalette.LinkVisited, t["accent"].darker(120))

    # Disabled group: fade text roles so disabled widgets read as such.
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, _with_alpha(t["fg"], 0.5))
    pal.setColor(QPalette.Disabled, QPalette.Highlight, t["mid"])
    pal.setColor(QPalette.Disabled, QPalette.HighlightedText, _with_alpha(t["fg"], 0.5))

    return pal


def build_stylesheet(xt: XtermSettings) -> str:
    """QSS patch for bits QPalette can't reach on Fusion."""
    t = _tones(QColor(xt.bg), QColor(xt.fg))
    handle = t["button"].name()
    track = t["base"].name()
    border = t["mid"].name()
    tooltip_bg = t["tooltip_bg"].name()
    fg = t["fg"].name()
    # QToolTip ignores QPalette::ToolTipBase/Text on Fusion in many environments
    # (it inherits the system tooltip palette instead). Setting bg + color in
    # QSS forces our derived theme to actually take effect.
    return f"""
QMenu::separator {{ background: {border}; height: 1px; margin: 4px 8px; }}
QToolTip {{
    background: {tooltip_bg};
    color: {fg};
    border: 1px solid {border};
    padding: 2px 4px;
}}

QScrollBar:vertical, QScrollBar:horizontal {{
    background: {track};
    border: none;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {handle};
    border-radius: 3px;
    min-height: 20px;
    min-width: 20px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ background: none; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
""".strip()


def apply_theme(app: QApplication, settings: Settings) -> None:
    """Push the palette + QSS onto the QApplication. Safe to call repeatedly."""
    app.setStyle("Fusion")
    app.setPalette(build_palette(settings.xterm))
    app.setStyleSheet(build_stylesheet(settings.xterm))
