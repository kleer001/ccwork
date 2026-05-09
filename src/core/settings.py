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
      },
      "ui": {
        "sidebar_side": "left",
        "sidebar_width": 240,
        "restore_last_repo": true,
        "desktop_notifications": true
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


# Migration chain. Each function takes a dict at version N and returns
# the dict at version N+1. Empty for now — the seam exists so future
# field renames/splits/removals are explicit and reviewable, instead of
# relying on `_raw` round-tripping plus default-application to silently
# absorb the change.
#
# Future example:
#     def _v1_to_v2(d: dict) -> dict:
#         """Split ui.sidebar_width into ui.sidebar.{width, side}."""
#         ui = d.get("ui", {})
#         ui["sidebar"] = {"width": ui.pop("sidebar_width", 240), ...}
#         return d
#     _MIGRATIONS = {1: _v1_to_v2}
_MIGRATIONS: dict[int, "Callable[[dict[str, Any]], dict[str, Any]]"] = {}


def _migrate(data: dict[str, Any], from_version: int) -> dict[str, Any]:
    """Apply the migration chain from `from_version` up to SCHEMA_VERSION."""
    v = from_version
    while v < SCHEMA_VERSION:
        fn = _MIGRATIONS.get(v)
        if fn is None:
            log.warning(
                "settings: no migration from v%d to v%d — leaving as-is",
                v, v + 1,
            )
            break
        data = fn(data)
        v += 1
    return data


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
        # Make the Athena scrollbar drag with Btn1 like every other GUI on
        # earth. xterm's default is Xaw's quirky "Btn1=line-down, Btn2=drag,
        # Btn3=line-up" — left-click-drag does nothing, which is the #1
        # confused-user complaint. Scoped to the scrollbar widget only, so
        # Btn1 in the VT100 area (selection) and Btn2 anywhere (paste) are
        # untouched. Btn3 line-scroll-up stays at the Xaw default since we
        # only #override Btn1.
        args += [
            "-xrm",
            "XTerm*scrollbar.translations: #override"
            " <Btn1Down>: StartScroll(Continuous) MoveThumb() NotifyThumb() \\n"
            " <Btn1Motion>: MoveThumb() NotifyThumb() \\n"
            " <Btn1Up>: NotifyScroll(Proportional) EndScroll()",
        ]
        # Let OSC 50 resize/reface the font at runtime. xterm's default is
        # false (a shared-tty hardening); we embed our own xterm per repo so
        # the threat model is fine. Using the specific class path leaves
        # extra_args free to override.
        args += ["-xrm", "XTerm.vt100.allowFontOps: true"]
        args.extend(self.extra_args)
        return args


@dataclass
class UISettings:
    sidebar_side: str = "left"           # "left" | "right"
    sidebar_width: int = 240             # px; persisted across sessions
    restore_last_repo: bool = True       # auto-open last_focused_repo at launch
    desktop_notifications: bool = True   # gate ccwork-hook-sink's notify-send
    # "dot" = colored circle (default); "glyph" = colored "!"/"✓"/"·" — the
    # glyph variant is more legible at a glance and colorblind-friendlier.
    status_badge_style: str = "dot"
    # When True, the sidebar reorders itself by most-recent Claude activity
    # (Stop / Notification / UserPromptSubmit) ~2s after the last event.
    # User-driven STATUS_LAST_FOCUSED transitions are not "Claude activity"
    # and do not feed the sort.
    auto_arrange_repos: bool = False
    # When True, repos with a live terminal float to the top of the sidebar
    # and a small visual gap separates them from the inactive rows below.
    # Composes with auto_arrange_repos: grouping is the primary key, activity
    # recency the secondary sort within each group.
    group_active_repos: bool = True


@dataclass
class Settings:
    xterm: XtermSettings = field(default_factory=XtermSettings)
    ui: UISettings = field(default_factory=UISettings)
    # Path of the repo whose row was most recently selected. Drives the
    # violet "last-focused" dot so the user can spot where they left off
    # after closing and reopening ccwork.
    last_focused_repo: str | None = None
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

    # Schema migration: bring older on-disk shapes up to SCHEMA_VERSION
    # before the field-by-field unpacking below. Files predating the
    # version field are treated as v1 (the schema before any rename
    # ever happened).
    raw_version = data.get("version", 1)
    file_version = raw_version if isinstance(raw_version, int) else 1
    if file_version < SCHEMA_VERSION:
        data = _migrate(data, file_version)
    elif file_version > SCHEMA_VERSION:
        log.warning(
            "%s: schema v%d is newer than this build's v%d — best-effort load",
            p, file_version, SCHEMA_VERSION,
        )

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
    u_raw = data.get("ui", {}) if isinstance(data.get("ui"), dict) else {}
    u_def = UISettings()
    side = str(u_raw.get("sidebar_side", u_def.sidebar_side)).lower()
    if side not in ("left", "right"):
        side = u_def.sidebar_side
    badge_style = str(u_raw.get("status_badge_style", u_def.status_badge_style)).lower()
    if badge_style not in ("dot", "glyph"):
        badge_style = u_def.status_badge_style
    ui = UISettings(
        sidebar_side=side,
        sidebar_width=max(60, min(600, int(u_raw.get("sidebar_width", u_def.sidebar_width)))),
        restore_last_repo=bool(u_raw.get("restore_last_repo", u_def.restore_last_repo)),
        desktop_notifications=bool(u_raw.get("desktop_notifications", u_def.desktop_notifications)),
        status_badge_style=badge_style,
        auto_arrange_repos=bool(u_raw.get("auto_arrange_repos", u_def.auto_arrange_repos)),
        group_active_repos=bool(u_raw.get("group_active_repos", u_def.group_active_repos)),
    )

    last_focused = data.get("last_focused_repo")
    if not isinstance(last_focused, str):
        last_focused = None
    return Settings(xterm=xterm, ui=ui, last_focused_repo=last_focused, _raw=data)


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Write settings atomically, preserving any unknown keys from _raw."""
    p = path or default_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Start from whatever was on disk, overlay our dataclass view.
    payload: dict[str, Any] = dict(settings._raw)
    payload["version"] = SCHEMA_VERSION
    payload["xterm"] = asdict(settings.xterm)
    payload["ui"] = asdict(settings.ui)
    if settings.last_focused_repo:
        payload["last_focused_repo"] = settings.last_focused_repo
    else:
        payload.pop("last_focused_repo", None)
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
