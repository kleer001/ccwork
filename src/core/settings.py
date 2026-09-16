"""Persistent GUI settings.

File: `~/.config/ccwork/settings.toml`

```toml
version = 2

[xterm]
font_family = "Monospace"
font_size = 10
scrollback = 20000
scrollbar = "right"   # "right" | "left" | "none"
jump_scroll = true
bg = "#1e1e1e"
fg = "#d0d0d0"
extra_args = []

[ui]
sidebar_side = "left"
sidebar_width = 240
restore_last_repo = true
desktop_notifications = true
status_badge_style = "dot"
auto_arrange_repos = false
group_active_repos = true

[ui.layout]
row_height = 52
padding_x = 10
group_gap_h = 10
glyph_w = 14
glyph_gap = 4
active_stripe_w = 3
last_focused_stripe_w = 2

[ui.animation]
spinner_interval_ms = 100
arrange_step_min_ms = 80
arrange_step_max_ms = 220
sidebar_quiet_ms = 800
reorder_debounce_ms = 2000
splitter_debounce_ms = 300

[window]
geometry = ""    # base64(QMainWindow.saveGeometry()); app-managed
```

Mirrors the xterm knobs a konsole user typically cares about. Unknown keys
are preserved on save so manual edits survive — including user-added
comments, courtesy of tomlkit's document round-trip.

To apply a change: save the file and restart ccwork (constants are read
at startup, not live).

A legacy `settings.json` is migrated to `.toml` on first launch and the
old file is renamed to `settings.json.bak`.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit import TOMLDocument


log = logging.getLogger(__name__)

SCHEMA_VERSION = 2


def default_settings_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "ccwork" / "settings.toml"


def _legacy_json_path(toml_path: Path) -> Path:
    return toml_path.with_suffix(".json")


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
            # Skip xterm's own session-manager save/die callbacks. This alone
            # is NOT enough to keep the SM from restoring floating xterms on
            # login — Xt still registers whenever SESSION_MANAGER is set — so
            # the real opt-out is unsetting SESSION_MANAGER in the child env
            # (see TerminalHost.start). Kept as belt-and-suspenders.
            "+sm",
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
        # Also override <Btn1Up> so a drag-select writes to PRIMARY *and*
        # CLIPBOARD: middle-click paste keeps working (PRIMARY) while
        # Ctrl+V in another app pastes what was highlighted (CLIPBOARD).
        # The xterm default is select-end(SELECT, CUT_BUFFER0), which only
        # populates PRIMARY — so highlight-then-Ctrl+V silently pastes
        # whatever was on the clipboard last.
        args += [
            "-xrm",
            "XTerm*VT100.translations: #override"
            " <Btn4Down>: scroll-back(3,line) \\n"
            " <Btn5Down>: scroll-forw(3,line) \\n"
            " <Btn1Up>: select-end(PRIMARY, CLIPBOARD, CUT_BUFFER0) \\n"
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
        # Suppress xterm's auto-snap-to-bottom on every new tty line — the
        # user's scroll position stays sticky. Tradeoff: tailing live output
        # no longer auto-follows; use End / scroll-to-bottom to catch up.
        args += ["-xrm", "XTerm*scrollTtyOutput: false"]
        args.extend(self.extra_args)
        return args


@dataclass
class LayoutSettings:
    """Sidebar row geometry. Power-user knobs — TOML-only, no GUI control.

    Tweak these to make rows denser, badges chunkier, or stripes thicker.
    """
    row_height: int = 52
    padding_x: int = 10
    # Vertical gap painted above the first inactive row when grouping is on.
    group_gap_h: int = 10
    # Right-edge status / spinner column.
    glyph_w: int = 14
    glyph_gap: int = 4
    # Left-edge stripes: selection accent and "last focused" bookmark.
    active_stripe_w: int = 3
    last_focused_stripe_w: int = 2


@dataclass
class AnimationSettings:
    """Sidebar animation timing. Power-user knobs — TOML-only, no GUI control.

    Drop the spinner interval to make it spin faster; widen the arrange
    step bounds for slower / more dramatic reshuffles; raise the quiet
    window to make reshuffle gate more conservatively.
    """
    spinner_interval_ms: int = 100
    arrange_step_min_ms: int = 80
    arrange_step_max_ms: int = 220
    sidebar_quiet_ms: int = 800
    # Auto-arrange debounce: how long after the last Claude event we wait
    # before triggering a reshuffle.
    reorder_debounce_ms: int = 2000
    # Splitter-drag persist debounce.
    splitter_debounce_ms: int = 300


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
    # The user-navigation bookmark (RepoListModel._last_focused) lives on a
    # separate axis and does not feed the sort.
    auto_arrange_repos: bool = False
    # When True, repos with a live terminal float to the top of the sidebar
    # and a small visual gap separates them from the inactive rows below.
    # Composes with auto_arrange_repos: grouping is the primary key, activity
    # recency the secondary sort within each group.
    group_active_repos: bool = True
    # When True, intercept plain Ctrl+Z in the terminal and prompt before
    # forwarding it as SIGTSTP. In a shell Ctrl+Z suspends the foreground
    # process (typically Claude) and drops the user back at a bash prompt,
    # where the stopped session looks gone until `fg`. Toggled live from the
    # dialog's "Show this warning next time" checkbox and from the
    # Preferences UI.
    warn_on_ctrl_z: bool = True
    layout: LayoutSettings = field(default_factory=LayoutSettings)
    animation: AnimationSettings = field(default_factory=AnimationSettings)


@dataclass
class WindowState:
    """Main window geometry persisted across launches.

    `geometry` is base64-encoded bytes from `QMainWindow.saveGeometry()`,
    which opaquely encodes size + position + maximize/fullscreen state +
    which screen the window is on. Restored via `restoreGeometry(bytes)`
    in MainWindow.__init__.

    Not nested under UISettings because this is runtime state the app
    writes on the user's behalf, not a preference the user deliberately
    tunes — same posture as the top-level `last_focused_repo`.
    """
    geometry: str = ""  # base64(QMainWindow.saveGeometry())


@dataclass
class Settings:
    xterm: XtermSettings = field(default_factory=XtermSettings)
    ui: UISettings = field(default_factory=UISettings)
    window: WindowState = field(default_factory=WindowState)
    # Path of the repo whose row was most recently selected. Drives the
    # violet "last-focused" dot so the user can spot where they left off
    # after closing and reopening ccwork.
    last_focused_repo: str | None = None
    # Raw loaded document so unknown keys (and user comments) round-trip
    # on save. Empty document when Settings is built from defaults.
    _raw: TOMLDocument = field(default_factory=tomlkit.document, repr=False)


# ── load ──────────────────────────────────────────────────────────────────


def _coerce_xterm(raw: dict | None) -> XtermSettings:
    d = XtermSettings()
    raw = raw if isinstance(raw, dict) else {}
    return XtermSettings(
        font_family=str(raw.get("font_family", d.font_family)),
        font_size=int(raw.get("font_size", d.font_size)),
        scrollback=int(raw.get("scrollback", d.scrollback)),
        scrollbar=str(raw.get("scrollbar", d.scrollbar)),
        jump_scroll=bool(raw.get("jump_scroll", d.jump_scroll)),
        bg=str(raw.get("bg", d.bg)),
        fg=str(raw.get("fg", d.fg)),
        extra_args=list(raw.get("extra_args", d.extra_args)),
    )


def _coerce_layout(raw: dict | None) -> LayoutSettings:
    d = LayoutSettings()
    raw = raw if isinstance(raw, dict) else {}
    return LayoutSettings(
        row_height=int(raw.get("row_height", d.row_height)),
        padding_x=int(raw.get("padding_x", d.padding_x)),
        group_gap_h=int(raw.get("group_gap_h", d.group_gap_h)),
        glyph_w=int(raw.get("glyph_w", d.glyph_w)),
        glyph_gap=int(raw.get("glyph_gap", d.glyph_gap)),
        active_stripe_w=int(raw.get("active_stripe_w", d.active_stripe_w)),
        last_focused_stripe_w=int(raw.get("last_focused_stripe_w", d.last_focused_stripe_w)),
    )


def _coerce_animation(raw: dict | None) -> AnimationSettings:
    d = AnimationSettings()
    raw = raw if isinstance(raw, dict) else {}
    return AnimationSettings(
        spinner_interval_ms=int(raw.get("spinner_interval_ms", d.spinner_interval_ms)),
        arrange_step_min_ms=int(raw.get("arrange_step_min_ms", d.arrange_step_min_ms)),
        arrange_step_max_ms=int(raw.get("arrange_step_max_ms", d.arrange_step_max_ms)),
        sidebar_quiet_ms=int(raw.get("sidebar_quiet_ms", d.sidebar_quiet_ms)),
        reorder_debounce_ms=int(raw.get("reorder_debounce_ms", d.reorder_debounce_ms)),
        splitter_debounce_ms=int(raw.get("splitter_debounce_ms", d.splitter_debounce_ms)),
    )


def _coerce_ui(raw: dict | None) -> UISettings:
    d = UISettings()
    raw = raw if isinstance(raw, dict) else {}
    side = str(raw.get("sidebar_side", d.sidebar_side)).lower()
    if side not in ("left", "right"):
        side = d.sidebar_side
    badge_style = str(raw.get("status_badge_style", d.status_badge_style)).lower()
    if badge_style not in ("dot", "glyph"):
        badge_style = d.status_badge_style
    return UISettings(
        sidebar_side=side,
        sidebar_width=max(60, min(600, int(raw.get("sidebar_width", d.sidebar_width)))),
        restore_last_repo=bool(raw.get("restore_last_repo", d.restore_last_repo)),
        desktop_notifications=bool(raw.get("desktop_notifications", d.desktop_notifications)),
        status_badge_style=badge_style,
        auto_arrange_repos=bool(raw.get("auto_arrange_repos", d.auto_arrange_repos)),
        group_active_repos=bool(raw.get("group_active_repos", d.group_active_repos)),
        warn_on_ctrl_z=bool(raw.get("warn_on_ctrl_z", d.warn_on_ctrl_z)),
        layout=_coerce_layout(raw.get("layout") if isinstance(raw.get("layout"), dict) else None),
        animation=_coerce_animation(raw.get("animation") if isinstance(raw.get("animation"), dict) else None),
    )


def _coerce_window(raw: dict | None) -> WindowState:
    d = WindowState()
    raw = raw if isinstance(raw, dict) else {}
    return WindowState(
        geometry=str(raw.get("geometry", d.geometry)),
    )


def _settings_from_mapping(data: dict, raw_doc: TOMLDocument) -> Settings:
    xterm = _coerce_xterm(data.get("xterm"))
    ui = _coerce_ui(data.get("ui"))
    window = _coerce_window(data.get("window"))
    last_focused = data.get("last_focused_repo")
    if not isinstance(last_focused, str):
        last_focused = None
    return Settings(
        xterm=xterm, ui=ui, window=window,
        last_focused_repo=last_focused, _raw=raw_doc,
    )


def _migrate_json_to_toml(json_path: Path, toml_path: Path) -> Settings | None:
    """Read a legacy settings.json, write settings.toml, archive the .json.

    Returns the migrated Settings, or None if the file is missing/corrupt.
    The original is renamed to `<name>.json.bak` so the user has a fallback
    if the migration ever drops something we didn't expect.
    """
    if not json_path.exists():
        return None
    try:
        data = json.loads(json_path.read_text() or "{}")
    except json.JSONDecodeError as e:
        log.warning("legacy %s is not valid JSON (%s) — using defaults", json_path, e)
        return None
    if not isinstance(data, dict):
        return None
    # Build a fresh TOML document seeded with the migrated data so the
    # written file has stable section ordering and tomlkit-friendly types.
    doc = _build_document_from(data)
    settings = _settings_from_mapping(data, doc)
    save_settings(settings, toml_path)
    backup = json_path.with_suffix(json_path.suffix + ".bak")
    try:
        json_path.replace(backup)
        log.info("migrated %s → %s (original at %s)", json_path, toml_path, backup)
    except OSError as e:
        log.warning("could not archive %s: %s", json_path, e)
    return settings


def load_settings(path: Path | None = None) -> Settings:
    """Load settings from disk.

    Order of preference:
      1. `settings.toml` at the given (or default) path.
      2. Legacy `settings.json` next to it — migrated in place.
      3. Built-in defaults.
    """
    p = path or default_settings_path()
    if p.exists():
        try:
            doc = tomlkit.parse(p.read_text() or "")
        except Exception as e:  # tomlkit raises various ParseError subclasses
            log.warning("%s is not valid TOML (%s) — using defaults", p, e)
            return Settings()
        return _settings_from_mapping(dict(doc), doc)

    # No .toml — try a one-shot migration from .json.
    legacy = _legacy_json_path(p)
    migrated = _migrate_json_to_toml(legacy, p)
    if migrated is not None:
        return migrated
    return Settings()


# ── save ──────────────────────────────────────────────────────────────────


def _build_document_from(data: dict[str, Any]) -> TOMLDocument:
    """Build a fresh TOMLDocument from a plain dict (used during JSON migration).

    Comments aren't carried — there were none in the JSON. The resulting
    doc has clean section ordering matching the dataclass shape.
    """
    doc = tomlkit.document()
    doc["version"] = SCHEMA_VERSION
    # _coerce_* validates / clamps; round-tripping through them gives us the
    # exact same values save_settings will write.
    xterm_d = asdict(_coerce_xterm(data.get("xterm")))
    ui_obj = _coerce_ui(data.get("ui"))
    window_obj = _coerce_window(data.get("window"))
    last_focused = data.get("last_focused_repo")
    doc["xterm"] = xterm_d
    doc["ui"] = _ui_to_toml(ui_obj)
    doc["window"] = _window_to_toml(window_obj)
    if isinstance(last_focused, str) and last_focused:
        doc["last_focused_repo"] = last_focused
    return doc


def _ui_to_toml(ui: UISettings) -> dict[str, Any]:
    return {
        "sidebar_side": ui.sidebar_side,
        "sidebar_width": ui.sidebar_width,
        "restore_last_repo": ui.restore_last_repo,
        "desktop_notifications": ui.desktop_notifications,
        "status_badge_style": ui.status_badge_style,
        "auto_arrange_repos": ui.auto_arrange_repos,
        "group_active_repos": ui.group_active_repos,
        "warn_on_ctrl_z": ui.warn_on_ctrl_z,
        "layout": asdict(ui.layout),
        "animation": asdict(ui.animation),
    }


def _window_to_toml(window: WindowState) -> dict[str, Any]:
    return {
        "geometry": window.geometry,
    }


def _merge_into(container: Any, key: str, value: Any) -> None:
    """Update `container[key]` while preserving tomlkit comments on existing keys.

    Reassigning a whole table (`doc["xterm"] = {...}`) replaces it with a
    fresh tomlkit table, which drops every comment that lived inside.
    Recursing key-by-key keeps the surrounding annotations intact.
    """
    if isinstance(value, dict):
        if key not in container or not hasattr(container[key], "__setitem__"):
            container[key] = value
            return
        sub = container[key]
        for k, v in value.items():
            _merge_into(sub, k, v)
    else:
        container[key] = value


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Write settings atomically, preserving unknown keys and comments via tomlkit."""
    p = path or default_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Mutate the round-trip document in place so user comments stay put.
    doc = settings._raw if settings._raw else tomlkit.document()
    doc["version"] = SCHEMA_VERSION
    _merge_into(doc, "xterm", asdict(settings.xterm))
    _merge_into(doc, "ui", _ui_to_toml(settings.ui))
    _merge_into(doc, "window", _window_to_toml(settings.window))
    if settings.last_focused_repo:
        doc["last_focused_repo"] = settings.last_focused_repo
    elif "last_focused_repo" in doc:
        del doc["last_focused_repo"]
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(tomlkit.dumps(doc))
    os.replace(tmp, p)
    # Keep _raw in sync so the next save reuses the freshly-written document.
    settings._raw = doc


def write_default_settings_file(path: Path | None = None) -> Path:
    """Create a settings.toml with built-in defaults if none exists.

    If a legacy `settings.json` is present, it's migrated by `load_settings`
    on first call — this helper is intentionally a no-op in that case.

    Returns the path (existing or newly created). Safe to call on startup.
    """
    p = path or default_settings_path()
    if p.exists():
        return p
    legacy = _legacy_json_path(p)
    if legacy.exists():
        # Defer to load_settings → _migrate_json_to_toml so we don't
        # overwrite the migration with empty defaults.
        load_settings(p)
        return p
    save_settings(Settings(), p)
    return p
