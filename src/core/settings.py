"""Persistent GUI settings.

File: `~/.config/ccwork/settings.json`

    {
      "xterm": {
        "font_family": "Monospace",
        "font_size": 10,
        "scrollback": 20000,
        "scrollbar": "right",
        "jump_scroll": true,
        "bg": "#1e1e1e",
        "fg": "#d0d0d0",
        "extra_args": []
      }
    }

Mirrors the xterm knobs a konsole user typically cares about. Unknown keys
are preserved on save so manual edits survive.

To apply a change: save the file and restart ccwork (terminals read the
settings at spawn time, not live).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def default_settings_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "ccwork" / "settings.json"


@dataclass
class XtermSettings:
    font_family: str = "Monospace"
    font_size: int = 10
    scrollback: int = 20000
    scrollbar: str = "right"       # "right" | "left" | "none"
    jump_scroll: bool = True
    bg: str = "#1e1e1e"
    fg: str = "#d0d0d0"
    # Raw xterm flags appended verbatim. Use for features we don't expose
    # a typed field for (e.g. -class, -xrm "XTerm*cursorBlink: true", …).
    extra_args: list[str] = field(default_factory=list)

    def to_xterm_args(self) -> list[str]:
        """Translate this settings block into xterm CLI flags."""
        args: list[str] = [
            "-fa", self.font_family,
            "-fs", str(self.font_size),
            "-sl", str(max(0, int(self.scrollback))),
            "-bg", self.bg,
            "-fg", self.fg,
        ]
        if self.scrollbar == "right":
            args += ["-sb", "-rightbar"]
        elif self.scrollbar == "left":
            args += ["-sb", "-leftbar"]
        else:
            args += ["+sb"]  # explicitly disable
        if self.jump_scroll:
            args += ["-j"]
        # Bind mouse wheel to scrollback, and Ctrl+Shift+C / Ctrl+Shift+V
        # to clipboard copy/paste so Ctrl+C in the shell keeps sending
        # SIGINT. Not all xterm builds bake these in, so be explicit.
        args += [
            "-xrm",
            "XTerm*VT100.translations: #override"
            " <Btn4Down>: scroll-back(3,line) \\n"
            " <Btn5Down>: scroll-forw(3,line) \\n"
            " Ctrl Shift <Key>C: copy-selection(CLIPBOARD) \\n"
            " Ctrl Shift <Key>V: insert-selection(CLIPBOARD)",
        ]
        # Let OSC 50 resize/reface the font at runtime. xterm's default is
        # false (a shared-tty hardening); we embed our own xterm per repo so
        # the threat model is fine. Using the specific class path leaves
        # extra_args free to override.
        args += ["-xrm", "XTerm.vt100.allowFontOps: true"]
        args.extend(self.extra_args)
        return args


@dataclass
class Settings:
    xterm: XtermSettings = field(default_factory=XtermSettings)
    # Raw loaded JSON so unknown keys round-trip on save.
    _raw: dict[str, Any] = field(default_factory=dict, repr=False)


def load_settings(path: Path | None = None) -> Settings:
    """Load settings from disk. Missing / corrupt → built-in defaults."""
    p = path or default_settings_path()
    if not p.exists():
        return Settings()
    try:
        data = json.loads(p.read_text() or "{}")
    except json.JSONDecodeError as e:
        log.warning("%s is not valid JSON (%s) — using defaults", p, e)
        return Settings()
    if not isinstance(data, dict):
        log.warning("%s: expected object, got %s — using defaults", p, type(data).__name__)
        return Settings()

    x_raw = data.get("xterm", {}) if isinstance(data.get("xterm"), dict) else {}
    defaults = XtermSettings()
    xterm = XtermSettings(
        font_family=str(x_raw.get("font_family", defaults.font_family)),
        font_size=int(x_raw.get("font_size", defaults.font_size)),
        scrollback=int(x_raw.get("scrollback", defaults.scrollback)),
        scrollbar=str(x_raw.get("scrollbar", defaults.scrollbar)),
        jump_scroll=bool(x_raw.get("jump_scroll", defaults.jump_scroll)),
        bg=str(x_raw.get("bg", defaults.bg)),
        fg=str(x_raw.get("fg", defaults.fg)),
        extra_args=list(x_raw.get("extra_args", defaults.extra_args)),
    )
    return Settings(xterm=xterm, _raw=data)


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Write settings atomically, preserving any unknown keys from _raw."""
    p = path or default_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Start from whatever was on disk, overlay our dataclass view.
    payload: dict[str, Any] = dict(settings._raw)
    payload["version"] = SCHEMA_VERSION
    payload["xterm"] = asdict(settings.xterm)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(tmp, p)


def write_default_settings_file(path: Path | None = None) -> Path:
    """Create a settings.json with built-in defaults if none exists.

    Returns the path (existing or newly created). Safe to call on startup.
    """
    p = path or default_settings_path()
    if not p.exists():
        save_settings(Settings(), p)
    return p
