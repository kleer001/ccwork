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

# Live integration scripts (X11 required — these aren't pytest tests)
.venv/bin/python tests/live/check_focus_scoping.py   # load-bearing
.venv/bin/python tests/live/check_keys_dispatch.py
.venv/bin/python tests/live/check_f1_cheatsheet.py
.venv/bin/python tests/live/check_window_geometry.py
.venv/bin/python tests/live/probe_xgrabkey.py        # diagnostic only
```

`tests/live/` holds end-to-end verification scripts that launch a real
ccwork in a sandboxed `XDG_CONFIG_HOME`, focus it via `wmctrl -ia
<wid>` (matched by `WM_CLASS=main.py.ccwork`), inject keystrokes via
`libXtst`, and assert on log output and `wmctrl -l`. They are NOT
pytest tests — names are deliberately off the `*_test.py` glob so
pytest discovery skips them. Run individually. The README in that dir
documents each one's purpose; `check_focus_scoping.py` is the
load-bearing guard against the "shortcuts leak globally" regression
the user caught after the keybinding rework.

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
Add Repo / Quit / F1 / row-jumps / cycle / zoom are bound via a passive
`XGrabKey` on MainWindow's own X window plus a single
`QAbstractNativeEventFilter` on the `QApplication` (see
`MainWindow._install_global_keys` and `src/core/key_grab.py`). Grabbing
on `self.winId()` rather than the X root keeps the combos scoped to
ccwork's focus chain — they fire when sidebar / terminal / dialog has
focus and stay out of the way when another app is focused.
Namespace is `Ctrl+Shift+<letter|digit>` for window actions
(`Ctrl+Shift+P/O/Q` = prefs/add/quit, `Ctrl+Shift+1..9` = row jump),
plain `Ctrl` for zoom, `Ctrl+Tab` / `Ctrl+Shift+Tab` for cycle, `F1`
for the keyboard cheatsheet. **Why not Qt's `QAction` shortcut path:**
the XEmbed'd xterm isn't a Qt widget, so when it holds X input focus
Qt's normal shortcut chain never sees the press. The XGrabKey path
intercepts presses at the X-server level before xterm can consume them.
Plain `Ctrl+C` is **conditionally** grabbed via the same mechanism while
`ui.warn_on_ctrl_c` is True: the handler shows
`ctrl_c_warning.show_ctrl_c_warning` and only on confirm writes `0x03`
into the current `TerminalHost`'s PTY (so SIGINT still reaches the
foreground process group). The grab is installed/removed at runtime as
the user toggles the pref, so when off Ctrl+C reaches xterm with zero
indirection.
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
- The sidebar spans four modules: **`repo_model.py`** (`RepoListModel`, a
  `QAbstractListModel`; owns the `ROLE_*` roles and the Claude-event →
  state table), **`repo_delegate.py`** (`RepoDelegate`, the row painter),
  **`badge_theme.py`** (every glyph / color / label / spinner constant —
  the single theming source both the model and delegate read), and
  **`repo_sidebar.py`** (the `RepoSidebar` widget: list view, animation
  timers, context menu, badge picker). `repo_sidebar.py` re-exports the
  model / delegate / `ROLE_*` / `STATUS_*` names, so
  `from src.ui.repo_sidebar import …` keeps resolving for callers and tests.

  `badge_theme.py` is **config-driven**: built-in defaults (the solarized
  palette) are overlaid at import with an optional
  `~/.config/ccwork/badges.toml` (a separate file from `settings.toml`).
  Colors accept `#hex`, `rgb(r,g,b)` (0–255), `hsv(h,s,v)` (hue 0–360,
  saturation/value 0–255), or an SVG color name; glyphs are strings,
  frames are arrays, and the two statuses are `[statuses.done]` /
  `[statuses.attention]` sub-tables of `{color, glyph, label}`. Omitted
  keys keep their default; a malformed value (bad color, empty glyph,
  unknown key) fails loudly at startup via `load_badge_theme`. The module
  docstring carries the full example schema.

  The delegate reserves
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
  **Reshuffle is quiet-gated *and* animated:** both reshuffle paths —
  terminal-grouping on `set_terminal_active` and the activity-driven
  auto-arrange (fired after a 2 s debounce on Claude hook traffic) —
  funnel through `_maybe_walk()`, which sets `_arrange_pending=True` and
  calls `_check_pending_walk()`. The walk fires only when the sidebar
  has had no input — mouse hover, click, key, scroll, or selection
  change — for `SIDEBAR_QUIET_MS` (800 ms); otherwise the check
  re-arms an `_arrange_check_timer` for when the quiet window would
  next elapse. `_bump_activity()` pushes the timestamp forward; it's
  called from `eventFilter` (hooked on `_view` and its viewport for
  `MouseMove`/`HoverMove`/`MouseButtonPress`/`Enter`/`KeyPress`/`Wheel`/
  `FocusIn`), `_on_current_changed`, and `_on_context_menu`. We invert
  the question "is the user in the terminal?" because XEmbed makes
  *that* unanswerable from Qt — xterm keystrokes never reach the Qt
  event loop, and the programmatic `XSetInputFocus` inside
  `host.focus_child()` doesn't fire `QApplication.focusChanged`. But
  "is the sidebar quiet?" is fully observable Qt-side, and
  user-typing-in-xterm produces no Qt sidebar events, so the proxy is
  reliable.
  Once a walk starts, `_step_arrange` bubbles the topmost-mismatched id
  up by one position per tick via `RepoListModel.move_row_up` (single
  `beginMoveRows`/`endMoveRows`), recomputing the composed target each
  tick via `RepoListModel.target_order_ids(auto_arrange=,
  group_active=)`. Recomputing each tick makes the walk self-correcting
  — a new active repo or fresh activity event arriving mid-animation
  falls in line on the next step. The per-tick interval follows a sine
  ease-in-out: `ARRANGE_STEP_MAX_MS` (220 ms) at the first and last
  gaps, `ARRANGE_STEP_MIN_MS` (80 ms) in the middle. `total` is
  recomputed each tick by replaying the bubble algorithm in
  `_simulate_remaining_swaps` — a plain mismatch count overestimates
  when one id bubbles past several others (every row in between reads
  as "wrong" right now but resolves implicitly).
  `apply_terminal_grouping()` and `apply_auto_arrange()` (instant) are
  still used when toggling the preference on, where animation would
  feel laggy after the dialog closes.
  The working spinner uses one of five braille variants in
  `SPINNER_VARIANTS`, picked per `repo.id` via `spinner_for_id()`
  (`zlib.crc32` so the choice is stable across launches — Python's built-in
  `hash` is process-salted and would re-shuffle on every restart).

### 2. Core domain (`src/core/`)

Pure logic with no Qt-widget dependencies (some modules use `QObject`/signals
but no widgets):

- `settings.py` — `Settings = {xterm: XtermSettings, ui: UISettings, ...}`
  persisted to `~/.config/ccwork/settings.toml` via `tomlkit`. **Unknown
  keys *and user-added comments* round-trip via `_raw`** (a `TOMLDocument`),
  so hand-edited files survive a GUI save. A legacy `settings.json` is
  migrated in place on first launch and renamed to `settings.json.bak`.
  `XtermSettings.to_xterm_args()` is the single source of truth for spawn
  flags. `UISettings` nests `layout: LayoutSettings` (row geometry) and
  `animation: AnimationSettings` (spinner / bubble-walk / debounce timings)
  — these are **TOML-only power knobs** with no GUI control; tweak by
  hand and restart. The save path uses `_merge_into` (key-by-key) rather
  than table reassignment so in-section comments survive.
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
  If the directory referenced by `repo.path` is renamed or deleted on
  disk, the branch sub-line paints as `(path missing)` (distinct from
  `(detached)`, which is reserved for a genuine detached HEAD) — driven
  by `ROLE_PATH_MISSING` populated in `RepoListModel.refresh_branches`.
  Right-click → *Rebind to…* repoints the row at a chosen directory
  (validated with `is_git_root`); `display_name` is a derived property
  over `path` basename + emoji + instance, so renaming the directory
  and rebinding flows through without a separate "rename row" action.
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

`MainWindow._on_hook_event` is a thin dispatcher: it special-cases
`RepoAdded` (auto-add a row) and toggles the bell dot for idle events;
everything else routes through `RepoSidebar.apply_hook_event(event,
path, payload)` → `RepoListModel.apply_hook_event`, which owns the entire
event → state mutation table. The model knows seven Claude events:

  • `UserPromptSubmit` — clear any prior alert, mark working,
    `touch_activity()` the path. Self-healing for Esc-interrupted /
    crashed turns is automatic: `set_working(True)` no-ops when already
    True and `touch_activity` refreshes the recency stamp unconditionally.
  • `Stop` — clear working, set `STATUS_DONE`. Does **not** clear
    `_bg_agents`: detached subagents outlive the main turn and the ◌
    indicator is meant to surface exactly that.
  • `Notification` — set `STATUS_ATTENTION`. Does **not** touch working:
    `permission_prompt` fires mid-turn and the turn is still live, so
    the spinner keeps running underneath the attention dot.
  • `PreToolUse` — registered with matcher `Task`. Increments
    `_bg_agents[path]` iff `payload.tool_input.run_in_background` is
    True (`_is_background_task_dispatch`). Foreground `Task` calls
    block the turn, so the working spinner already covers them.
  • `SubagentStop` — decrements `_bg_agents[path]`, clamped at 0.
    Fires for both foreground and background subagents; the clamp
    absorbs the foreground decrements we never incremented for.
  • `SessionStart` — flips `_session_active[path] = True`. The ambient
    badge in the right-edge column switches from ▌ (bare terminal) to
    ⠿ (Claude is here) when no higher-priority alert is showing.
  • `SessionEnd` — flips `_session_active[path] = False` AND
    cascade-clears `_status`, `_working`, `_bg_agents`, `_turn_started`
    for this path. The session is over, so those signals are stale and
    would otherwise mask the new ▌ ambient indicator. Done inline in
    `_set_session_active(active=False)` rather than via the public
    mutators so the whole transition lands in a single dataChanged
    emission.

`MainWindow` no longer keeps a parallel id-keyed `_working` set; the
quit-confirm derives its list on demand via `model.is_working(path)`
intersected with running terminals.

The right-edge column paints one badge per row, picked by priority
(highest first):

  1. `STATUS_ATTENTION` (red dot) — wins over the spinner so a
     `permission_prompt` is glanceable even when desktop notifications
     are off (the bell aggregates across repos, so it can't identify
     *which* repo is waiting).
  2. Working spinner — braille frames from `SPINNER_VARIANTS`, picked
     per-id via `spinner_for_id`, paints while the main turn is live.
  3. `STATUS_DONE` (green dot) — paints after `Stop` until the next
     `UserPromptSubmit` clears it.
  4. `BG_AGENT_FRAMES` twinkle (`·→✦→✶→❋→✶→✦` in solarized cyan) —
     paints when the main turn is idle but `_bg_agents[path] > 0`
     (one or more `Task` calls dispatched with `run_in_background=True`
     and `SubagentStop` hasn't balanced them yet).
  5. Ambient terminal-state — only when the row has a live terminal
     and no higher badge applies. `SESSION_ACTIVE_GLYPH` (⠿, dense
     braille) when `_session_active[path]` is True; otherwise
     `TERMINAL_ONLY_GLYPH` (▌, left-half-block text cursor). Both in
     `AMBIENT_COLOR` (solarized base01) so they read as quiet ambient
     presence, not alerts.

Both animations (working spinner + bg-agent twinkle) share the
delegate's `spinner_frame` counter and the `_spinner_timer`, which is
started whenever `any_working() or any_bg_agents()` is true. The
spinner timer keeps ticking while attention is shown, so once the
user approves and the next event clears the status, the spinner
reappears for the rest of the turn. The left-edge **last-focused stripe** is on a separate
axis: stored in `RepoListModel._last_focused` (single value), surfaced
via `ROLE_LAST_FOCUSED`, mutated only by `set_last_focused()`. Claude
events never touch it; user navigation never touches `_status`.

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
- **Badge glyphs / colors / labels live in `badge_theme.py`** — the single
  theming source the model (tooltips) and delegate (painting) both read,
  overridable via `~/.config/ccwork/badges.toml`. A new badge cue adds its
  glyph + color + label there (colors go through `_parse_color`, so they
  accept hex / `rgb()` / `hsv()` / SVG names) rather than hardcoding a
  `QColor(...)` or glyph literal in the delegate's paint method.
- **User-state and Claude-alert state are storage-separate.** Last-focused
  lives in `RepoListModel._last_focused` (one path, its own role
  `ROLE_LAST_FOCUSED`). Claude alerts live in `_status` (DONE/ATTENTION
  only) and `_working`. A Claude event must never mutate `_last_focused`;
  a user navigation must never mutate `_status` or `_working`. If you add
  a new cue, decide first which side it belongs on, then give it its own
  field + role + mutator.
- **Auto-arrange sort is keyed off `_last_activity`**, stamped only by
  the three Claude events (via `set_status` for DONE/ATTENTION,
  `set_working` on the off→on edge for UserPromptSubmit, plus
  `touch_activity` for the explicit case where UPS arrives while
  working is already True). Setting `_last_focused` does not stamp.
- **The right-edge badge column is reserved for Claude alerts and
  terminal state.** Working spinner, `STATUS_DONE`, `STATUS_ATTENTION`,
  the animated `BG_AGENT_FRAMES` twinkle, and the ambient
  `SESSION_ACTIVE_GLYPH` / `TERMINAL_ONLY_GLYPH` indicators all paint
  there in the priority order above. The last-focused bookmark renders
  as a thin left-edge stripe in a distinct paint pass so the two never
  compete for the same eye-level.
- **`apply_hook_event` is the single entry point for hook-driven state
  changes.** Don't sequence `set_working` + `set_status` + `clear_status`
  ad-hoc from new call sites — extend the event → mutation table on
  `RepoListModel.apply_hook_event` instead, and add the event to
  `_CLAUDE_STATE_EVENTS` if it should drive the spinner timer +
  reorder schedule.
- **Terminals are keyed by `repo.id`, not `repo.path`.** `MainWindow._terminals`
  is a dict of repo ids so duplicate rows on the same path get
  independent xterms. Hook events arrive with `cwd` and the sidebar
  state is path-keyed — `apply_hook_event(event, path)` broadcasts to
  every duplicate row. The quit-confirm derives its working-id list on
  demand from `model.is_working(path)` rather than maintaining a
  parallel set. Per-session routing is future work.
- Tests use `QT_QPA_PLATFORM=offscreen`. The shared `qapp` fixture and
  `StubHookServer` stand-in live in `tests/conftest.py` — depend on those
  rather than re-rolling them per file.

## Install / packaging

`install.sh` is the user-facing installer; `bootstrap.sh` is a curl-pipe
wrapper around it. Both are idempotent, write only under `$HOME`, back up
every touched file under `~/.local/share/ccwork/backups/`, and support
`--dry-run` and `--uninstall`. The installer wires the hook sink into
`~/.claude/settings.json` using the `ccwork-hook-sink` marker so uninstall
can locate and strip those entries. Hooks installed: `Stop`,
`Notification`, `UserPromptSubmit`, `PreToolUse` (matcher `Task`),
`SubagentStop`, `SessionStart`, and `SessionEnd`. The installer strips
any prior ccwork hooks before writing, so re-running `install.sh` is
the upgrade path when the set changes.
