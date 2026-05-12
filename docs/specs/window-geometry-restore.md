# Window geometry restore

Save and restore the main window's size, position, and maximize/fullscreen
state across launches.

## Motivation

Today every launch hard-codes `self.resize(1280, 820)` in
`MainWindow.__init__` (see `src/ui/main_window.py:70`) and lets the WM
centre the result. On multi-monitor setups it's jarring: the user drags
ccwork to their side-monitor, quits, relaunches, finds it back on the
primary at default size. Every IDE and terminal emulator on this user's
desktop already remembers where it was — ccwork should too.

## Scope

**In:**
- Window size and screen position.
- Maximize / fullscreen state.

**Out:**
- Per-monitor multi-instance memory (ccwork is a single window — there's
  nothing to disambiguate).
- Workspace / virtual-desktop number. X11-specific, WM's job.
- Splitter sizes / sidebar width. Already persisted via
  `UISettings.sidebar_width` (see `MainWindow._on_splitter_moved` at
  `src/ui/main_window.py:215`).

## Design

### Storage

`QMainWindow.saveGeometry()` returns a `QByteArray` that opaquely encodes
geometry + maximize state + which screen the window is on.
`restoreGeometry(bytes)` does the inverse, including clamping a restored
window to currently-available screen real estate (see Edge cases).

The blob is binary. To survive `settings.toml`, **base64-encode it as a
TOML string**.

Add a new top-level section `[window]` with its own dataclass. **Not
under `[ui]`** — `UISettings` is for preferences the user deliberately
tunes (sidebar side, badge style, notifications). Window geometry is
*runtime state* the app writes on the user's behalf, peer-status with
the existing top-level `last_focused_repo`. Same reasoning as why
`last_focused_repo` is not in `UISettings`.

```python
@dataclass
class WindowState:
    geometry: str = ""  # base64(QMainWindow.saveGeometry())
```

Add to `Settings`:

```python
@dataclass
class Settings:
    xterm: XtermSettings = field(default_factory=XtermSettings)
    ui: UISettings = field(default_factory=UISettings)
    window: WindowState = field(default_factory=WindowState)
    last_focused_repo: str | None = None
    _raw: TOMLDocument = field(default_factory=tomlkit.document, repr=False)
```

A single opaque `geometry` field suffices — `saveGeometry()` already
encodes maximize/fullscreen. A separate `maximized: bool` would
double-source the truth.

### Alternative considered: `QSettings`

The textbook Qt approach is `QSettings(org, app)`, which writes to
`~/.config/<org>/<app>.conf` and accepts a `QByteArray` directly.
Rejected because it introduces a second config file. ccwork's deliberate
UX is "one TOML file you can `cat`, edit, and version-control". The
price is base64 ugliness in one field — acceptable, isolated to its
own section.

### Save trigger

Save in `MainWindow.closeEvent`, **after** the working-session
confirmation short-circuit (`event.ignore()` path), so a cancelled quit
doesn't persist a transient geometry. Concretely, in the existing
`closeEvent` at `src/ui/main_window.py:581`:

```python
def closeEvent(self, event):
    # ... existing working-session prompt ...
    if ans != QMessageBox.Yes:
        event.ignore()
        return
    # NEW: capture geometry before tearing down terminals.
    self._persist_window_state()
    for host in list(self._terminals.values()):
        host.stop()
    self._terminals.clear()
    super().closeEvent(event)
```

Do **not** also hook `moveEvent` / `resizeEvent` with a debounce. The
splitter pattern at `_on_splitter_moved` exists because the splitter has
no "drag finished" signal. Top-level windows do — `closeEvent` is the
natural commit point, and saving on every drag frame just thrashes
`settings.toml` for no user-visible benefit.

A failed save here must not block quit. Reuse the `_persist_settings_now`
pattern (try / log / continue) at `src/ui/main_window.py:231`.

### Restore trigger

In `MainWindow.__init__`, replace the unconditional `self.resize(1280, 820)`
with a fallback-only call:

```python
self.resize(1280, 820)  # fallback if no saved geometry
blob = self._settings.window.geometry
if blob:
    try:
        ok = self.restoreGeometry(base64.b64decode(blob.encode("ascii")))
        if not ok:
            log.info("restoreGeometry returned False — using default size")
    except (ValueError, binascii.Error) as e:
        log.warning("corrupt window.geometry blob (%s) — using default", e)
```

`restoreGeometry` returns `bool`; `False` means Qt rejected the blob
(version skew, magic-number mismatch). Treat that and a base64 decode
error identically: log and fall through to the default size. The
`resize(1280, 820)` call before the restore is intentional — if restore
fails, we've already set a sane size.

**Do not** call `restoreGeometry` before `setCentralWidget`. Qt
documents that geometry restore should happen after the window's child
hierarchy is in place; doing it earlier can produce sized-but-unlaid-out
windows on first show. The simplest fix is to add the restore at the end
of `__init__`, after `setCentralWidget` and the existing
`QTimer.singleShot(0, ...)` for `restore_last_repo`.

### First-run UX

No saved geometry (`window.geometry == ""`) → fall through to the
existing 1280×820 default. This is the only first-run path and matches
today's behavior exactly. Document inline that the empty-string default
is intentional, not a bug.

## Files touched

- `src/core/settings.py` — add `WindowState` dataclass, add `window`
  field on `Settings`, add `_coerce_window`, plumb through
  `_settings_from_mapping`, `save_settings` (via a new
  `_window_to_toml` helper merged with `_merge_into`), and
  `_build_document_from`. Mirror the structure of the existing
  `LayoutSettings` / `AnimationSettings` plumbing — they're the closest
  precedent for a small nested dataclass under a top-level key.
- `src/ui/main_window.py` — in `__init__`, attempt base64 decode +
  `restoreGeometry` after `setCentralWidget`; in `closeEvent`, call a
  new `_persist_window_state()` helper after the working-session prompt
  passes. Helper writes `self._settings.window.geometry = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")` and reuses
  `_persist_settings_now`.
- `tests/test_settings.py` — round-trip tests (see below).

## Edge cases

- **Monitor disappeared between save and restore.** `restoreGeometry`
  clamps off-screen windows to the nearest visible screen. Verify by
  hand on a hot-unplugged external; no code needed.
- **Maximized → unmaximized between launches.** `saveGeometry` encodes
  both the maximized flag and the "normal geometry" Qt restores to on
  unmaximize. Blob round-trips correctly without tracking state separately.
- **Very small saved sizes** (user shrunk to 200×150 before quitting).
  Qt restores faithfully. If this becomes a problem, enforce a minimum
  via `self.setMinimumSize(...)` — but don't reject the blob.
- **Corrupt base64 blob.** Hand-edit in `settings.toml`, partial write
  from a crash, anything. Catch `binascii.Error` / `ValueError`, log
  at WARNING, fall through to the 1280×820 default. Never raise out of
  `__init__`.
- **Qt version skew.** A blob from PySide6 6.6 may be rejected by 6.8
  (different magic inside the QByteArray). `restoreGeometry` returns
  `False`; we treat that identically to a decode failure. Next quit
  overwrites the bad blob.
- **DPI change between save and restore** (docked vs. undocked). Qt's
  high-DPI handling normalizes encoded geometry to logical pixels — a
  1280-wide window saved at 1.0x restores to 1280 logical px at 2.0x.
  No action needed.

## Tests

In `tests/test_settings.py`, mirroring the existing patterns:

- `test_window_state_defaults` — `WindowState().geometry == ""`.
- `test_window_state_round_trip` — set a non-empty geometry string
  through `Settings.window.geometry`, `save_settings` → `load_settings`,
  assert it survives byte-for-byte. The value can be a synthetic
  base64 string (`base64.b64encode(b"hello").decode()`) — settings.py
  doesn't validate that the blob is a real Qt geometry payload, only
  that it round-trips.
- `test_window_state_survives_unknown_keys_and_comments` — extends
  `test_round_trip_preserves_user_comments` to also include a
  hand-edited `[window]` section with a `# comment` above it; verify
  the comment survives a GUI save (this is what `_raw` and `_merge_into`
  exist for).
- `test_corrupt_window_geometry_falls_back` — write a `settings.toml`
  with `[window]\ngeometry = "not-valid-base64!!!"` and assert
  `load_settings` returns successfully (load itself doesn't decode the
  blob — that happens in `MainWindow.__init__`).

A GUI integration test for the `__init__` / `closeEvent` save+restore
cycle is possible under `QT_QPA_PLATFORM=offscreen` (see the `qapp`
fixture in `tests/test_preferences_dialog.py`), but lower priority than
the settings round-trip — TOML serialization is what historically breaks.

## Out of scope

- Per-monitor positioning logic. Qt handles it adequately out of the box.
- Workspace / virtual-desktop restore (X11-EWMH-specific; the WM owns this).
- Multi-window app state. ccwork is single-window today; revisit if and
  when a second top-level window is added.
- A Preferences toggle for "remember window position". Standard-enough
  behavior that a knob isn't worth the surface area. Users who dislike
  it can hand-edit `window.geometry = ""` between launches.
