# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Run & test

The project ships with `.venv/`. The `ccwork` launcher (`bin/ccwork`) prefers
`.venv/bin/python` and falls back to `python3`.

```bash
# Launch the GUI
./bin/ccwork
# or
.venv/bin/python -m src.main

# Full test suite (Qt needs a platform — offscreen is fine in CI)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q

# Single test or file
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings.py -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings.py::test_ui_settings_min_width_enforced_on_load -q

# Increase log verbosity for the running app
CCWORK_LOG=DEBUG ./bin/ccwork
```

There is no separate lint/format step configured. Dependencies are pinned in
`requirements.txt` (`PySide6>=6.6`, `pytest`, `pytest-cov`).

## Platform constraint

**Linux + X11 or XWayland only.** The GUI embeds real `xterm` processes via
XEmbed (`-into self.winId()`), which has no Wayland equivalent. `src/main.py`
forces `QT_QPA_PLATFORM=xcb` when `WAYLAND_DISPLAY` is set, before any Qt
import. Don't move that block.

## Architecture

The app is a Qt frontend that orchestrates external `xterm` processes and
listens for Claude Code hook events over a Unix socket. Three subsystems
collaborate:

### 1. UI layer (`src/ui/`)

`MainWindow` lays out a sidebar + a `QStackedWidget` of `TerminalHost`s (one
per repo, swapped on selection). There is no menu bar — Preferences /
Add Repo / Quit are window-level `QAction`s on `Ctrl+,` / `Ctrl+O` / `Ctrl+Q`.
The top bar holds, right-to-left: the gear (Preferences), the 🔔 unread
indicator, and a 🔊/🔇 toolbutton mirroring the "Show desktop
notifications" preference (single source of truth:
`Settings.ui.desktop_notifications`).

- `terminal_host.py` spawns `xterm -into <winId>` via `QProcess`, polls for
  the reparented child window through `src/core/x11.py`, then resizes the X
  window in lockstep with the Qt widget so the PTY gets `SIGWINCH`.
- `qt_theme.py` derives a `QPalette` from `XtermSettings.bg`/`.fg` so the
  GUI chrome matches the embedded terminal. It forces `setStyle("Fusion")` —
  native styles (Breeze, Adwaita) ignore palette overrides on Window/Base.
- `repo_sidebar.py` owns its own `QAbstractListModel`. The delegate reserves
  a right-edge column for a status badge (colored dot or glyph) that
  auto-hides only when fewer than ~4 chars of row text would remain — this
  is what lets the splitter drag down to ~6 chars wide without garbling.
  When `ui.group_active_repos` is on (default), rows with a live terminal
  float to the top via `RepoListModel.apply_terminal_grouping()`, and the
  delegate paints a `GROUP_GAP_H` strip above the first inactive row
  (`_is_group_boundary` driven by `ROLE_HAS_TERMINAL`). `setUniformItemSizes`
  is therefore off — the boundary row's `sizeHint` is taller. Grouping
  composes with auto-arrange: it's applied after the activity sort, so
  "has terminal" wins over recency.
  **Reshuffle is deferred:** `RepoSidebar.set_terminal_active` does not
  reorder immediately — it sets `_regroup_pending` and lets the *next*
  selection change trigger `apply_terminal_grouping()` (consumed at the
  start of `_on_current_changed`, before `repo_selected.emit`). Otherwise
  the row the user just clicked yanks out from under the cursor, which
  reads as "the wrong repo got selected" even though persistent indexes
  preserve the logical selection.
  The working spinner uses one of five braille variants in
  `SPINNER_VARIANTS`, picked per `repo.id` via `spinner_for_id()`
  (`zlib.crc32` so the choice is stable across launches — Python's built-in
  `hash` is process-salted and would re-shuffle on every restart).

### 2. Core domain (`src/core/`)

Pure logic with no Qt-widget dependencies (some modules use `QObject`/signals
but no widgets):

- `settings.py` — `Settings = {xterm: XtermSettings, ui: UISettings, ...}`
  persisted to `~/.config/ccwork/settings.json`. **Unknown keys round-trip
  via `_raw`**, so older ccwork versions don't drop fields written by newer
  ones. `XtermSettings.to_xterm_args()` is the single source of truth for
  spawn flags.
- `repo_store.py` — `~/.config/ccwork/repos.json`. Plain value object; no
  file watcher. Each `Repo` carries a uuid `id`, an `instance` integer,
  and an optional `emoji` string. Duplicate paths are allowed (multiple
  parallel sessions on one repo); `instance` is the Roman-numeral suffix
  (0 = bare basename, ≥1 = `(I)`, `(II)`, …). Sticky while ≥2 rows share
  a path; resets to 0 when the count drops back to 1; sequence restarts
  on the next duplicate add. `emoji` is a per-id (not per-path) leading
  prefix on `display_name` — surfaced in the UI as the row "badge"
  (right-click → *Set badge…*), opt-in, empty string means "no badge".
  The badge dialog is in `repo_sidebar.py`: `BADGE_GALLERY` is the
  25-glyph quick-pick list; `_find_emoji_picker()` probes
  `EMOJI_PICKER_CANDIDATES` for an external one-shot picker. The
  persisted JSON key stays `emoji` for back-compat.
- `terminal_session.py` — builds the argv passed to `TerminalHost`. Sets
  `CCWORK_GUI=1` in the child env (the gate the hook sink checks). Launches
  bash with `--rcfile bin/ccwork-bashrc` so ccwork's `bin/` wins on `PATH`
  regardless of the user's `.bashrc`.
- `hook_server.py` — `QLocalServer` listening at
  `$XDG_RUNTIME_DIR/ccwork/ccwork.sock`. Each newline-terminated JSON line
  becomes a single `event_received(dict)` signal. Malformed lines are
  logged and dropped; the GUI never raises on hook input.
- `xterm_osc.py` — applies bg/fg/cursor/font live by writing OSC escapes to
  the xterm's PTY slave (`/dev/pts/N`). Settings xterm reads only at
  startup (scrollback, scrollbar, `-xrm`) require respawn; `apply_live()`
  returns the list of knobs that couldn't be applied.
- `x11.py` — minimal `ctypes` wrapper around libX11 for window-geometry
  ops. Everything else goes through Qt.

### 3. External integration (`bin/`)

- `bin/ccwork-hook-sink` — wired into Claude Code's Stop/Notification hooks
  by `install.sh`. Reads the hook payload from stdin, wraps it as
  `{"event": $CCWORK_EVENT, "cwd": $PWD, "ts": …, "payload": …}`, writes
  one line to the ccwork socket. **Gated by `CCWORK_GUI=1`** — outside the
  ccwork GUI it drains stdin and exits 0, so plain `claude` use isn't
  affected. Failure to reach the socket is silent by design (hooks must
  never break the user's session).
- `bin/claude` — `PATH`-shadow wrapper for `claude`. Pings the ccwork
  socket with a `RepoAdded` event for unregistered git roots so the
  sidebar auto-populates, then execs the real `claude` with the user's
  args untouched.

### Event flow

```
Claude Code hook ─▶ ccwork-hook-sink ─▶ unix socket ─▶ HookServer
                                                            │
                                                            ▼
                                          MainWindow._on_hook_event
                                            ├─ sidebar status badge
                                            ├─ working spinner toggle
                                            └─ desktop notify-send (gated)
```

`UserPromptSubmit` clears any prior status and sets working=True; `Stop`/
`Notification` clear working and set the corresponding status. Working and
status are mutually exclusive in the UI by construction.

## Conventions worth knowing

- **Don't catch hook-input errors at the call site** — `HookServer` already
  swallows malformed lines. Bubbling them further would let a bad client
  crash the GUI, which the project explicitly avoids.
- **Sidebar width is splitter-only** — there is no spinbox. Drag persists
  via debounced `splitterMoved` (300 ms). Floor is 60 px.
- **`Settings._raw` matters.** When adding a new settings field, update
  both the dataclass and `load_settings()`; `save_settings()` serializes
  via `asdict` over `_raw`, so unknown keys survive.
- **xterm spawn args are centralized** in `XtermSettings.to_xterm_args()`.
  Don't append flags ad-hoc from the UI layer — extend the settings dataclass.
- **Auto-arrange sort excludes `STATUS_LAST_FOCUSED`.** The violet "last
  focused" mark is set by user navigation, not Claude. `_last_activity` is
  bumped only by Stop / Notification / UserPromptSubmit. If you add a new
  status, decide deliberately whether it represents Claude activity (and
  therefore should stamp the timestamp) or user state (and should not).
- **The right-edge badge column is reserved for Claude alerts.** Working
  spinner, `STATUS_DONE`, `STATUS_ATTENTION` paint there. `STATUS_LAST_FOCUSED`
  is rendered as a thin left-edge stripe (a quiet bookmark) so a frequently-
  navigating user doesn't tune the alert column out as noise. If you add
  another status, decide whether it's a Claude alert (right-edge column,
  add to `STATUS_COLORS`/`STATUS_GLYPHS`) or a user-state cue (paint
  somewhere else).
- **Terminals are keyed by `repo.id`, not `repo.path`.** `MainWindow._terminals`
  and `_working` are dicts/sets of repo ids so duplicate rows on the same
  path get independent xterms. Hook events arrive with `cwd` and broadcast
  to every matching id (per-session routing is future work). Sidebar
  per-path state (`_branches`, `_status`, working spinner) stays
  path-keyed — broadcast across duplicates is the intended UX.
- Tests use `QT_QPA_PLATFORM=offscreen`. The `qapp` fixture in
  `tests/test_preferences_dialog.py` is the pattern to follow when a test
  needs a `QApplication`.

## Install / packaging

`install.sh` is the user-facing installer; `bootstrap.sh` is a curl-pipe
wrapper around it. Both are idempotent, write only under `$HOME`, back up
every touched file under `~/.local/share/ccwork/backups/`, and support
`--dry-run` and `--uninstall`. The installer wires the hook sink into
`~/.claude/settings.json` using the `ccwork-hook-sink` marker so uninstall
can locate and strip those entries.
