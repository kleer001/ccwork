# Specs Roadmap

Implementation plan for the seven specs in `docs/specs/`. Status was last
audited **2026-05-13**. One prerequisite landed since the original write-up
— the application-wide keybinding mechanism — and one spec (row-jump) is
partially shipped as a side-effect of that prerequisite. The remaining six
specs are still pending, in the Wave order they were originally sequenced in.

All seven are still rated **Small** difficulty. The bottleneck is
`src/ui/main_window.py` (touched by 6 of 7), but the edits land in disjoint
zones (`_install_global_keys`, `__init__`, `closeEvent`, terminal lifecycle,
signal wiring). Sequencing matters more than parallelism for a solo dev —
order below is chosen to keep each PR self-contained and to land the
cross-referencing specs last.

## Status

| Item | Status | Notes |
|---|---|---|
| Keybinding infrastructure | shipped 2026-05-13 | Root `XGrabKey` + single `QAbstractNativeEventFilter` on the `QApplication`. Lives in `src/core/key_grab.py` + `MainWindow._install_global_keys`. Replaces the QAction / `_install_shortcuts` approach (which never fired while xterm held X focus). Verified live via XTest injection — see `docs/specs/SMOKE-TEST.md`. |
| 1. working-elapsed-time | shipped 2026-05-13 | `RepoListModel._turn_started` dict + `mark_turn_start` / `clear_turn_start` mutators + module-level `_format_elapsed`. Tooltip on working rows appends `Working 27s` / `1m 23s` / `1h 5m`. 7 tests in `test_repo_sidebar_working_elapsed.py`. |
| 2. window-geometry-restore | shipped 2026-05-13 | New top-level `[window]` section with base64-encoded `QMainWindow.saveGeometry()`. Restore in `__init__`, persist in `closeEvent`. Corrupt blob → WARNING log only (per user feedback: log-only, no status-bar, no modal). 4 tests in `test_settings.py`; live-verified via XTest-injected Ctrl+Shift+Q. |
| 3. row-context-path-actions | shipped 2026-05-13 | *Open in file manager* (xdg-open via `QProcess.startDetached`, disabled + tooltip when missing) + *Copy path* (QClipboard + new `path_copied` signal flashing a status-bar confirmation in `MainWindow._on_path_copied`). Refactored `_on_context_menu` into a `_build_context_menu` helper for testability. 7 tests in `test_repo_sidebar_path_actions.py`. |
| 4. working-count-in-title | pending | |
| 5. row-jump (was alt-n-row-jump) | **partial** | Binding on `Ctrl+Shift+1`..`Ctrl+Shift+9` shipped via the infrastructure above; `_jump_to_row` slot wired and verified. Remaining: status-bar `"No repo at slot N"` transient + the `tests/test_alt_row_jump.py` unit test. |
| 6. empty-state-placeholder | pending | |
| 7. keyboard-cheatsheet | pending | |

### Note on stale spec files

The six pending spec files in `docs/specs/` were written before the keybinding
rework and still reference `_install_shortcuts`, `_install_zoom_grabs`,
`_ZOOM_KEYS`, `_WINDOW_SHORTCUT_KEYS`, the `Alt+1..9` namespace, and the
QAction/`Qt.ApplicationShortcut` model. The design hooks they describe remain
valid — they just relocated. When implementing each spec, update its file
in-place to point at:

- `MainWindow._install_global_keys` (one entry in the `bindings` list per
  shortcut, plus a method on `MainWindow` for the callback)
- `TerminalHost._install_button_grabs` (pointer-button grabs only — Ctrl+wheel,
  RMB; the keyboard grab is no longer per-container)
- `KeyGrabFilter.register(keysym, mods, callback)` for the dispatch side
- `Ctrl+Shift+N` instead of `Alt+N` for the row-jump namespace; this is the
  new convention because xterm's `metaSendsEscape` consumes Alt+digit as
  `ESC+digit` on the PTY, which broke the original `Alt+N` design

## Resolved decisions

| Spec | Decision | Source |
|---|---|---|
| (infrastructure) | Shortcuts use **root-window XGrabKey** on Qt's own xcb connection (`QX11Application.display()`), dispatched via one `QAbstractNativeEventFilter`. Mirrors QHotkey/CopyQ. Per-`TerminalHost` grabs were a dead-end. | claude (2026-05-13) |
| (infrastructure) | Shortcut namespace is **Ctrl+Shift+\<letter\|digit\>** for window actions; plain Ctrl for zoom; F-keys reserved. Readline / stty / claude leave shifted-Ctrl alone, so a missed grab is harmless. | claude (2026-05-13) |
| row-jump | Empty-slot feedback: status-bar `"No repo at slot N"`, 1.5 s transient | user |
| row-jump | Namespace moved from `Alt+N` to `Ctrl+Shift+N` because xterm `metaSendsEscape` consumes Alt+digit | claude (2026-05-13) |
| empty-state-placeholder | Logo fallback: **silently hide image**, keep heading + hints | user |
| empty-state-placeholder | **No F1 hint in Wave 2** — cheatsheet PR (Wave 3) appends it | user |
| empty-state-placeholder | Subhead: full-contrast palette text (simpler; both options OK per spec) | claude |
| empty-state-placeholder | Hints reference current shortcut names: `Ctrl+Shift+O` (add), right-click, `Ctrl+Shift+P` (preferences); not the pre-rework `Ctrl+O` / `Ctrl+,` | claude (2026-05-13) |
| row-context-path-actions | **No separator** between Clone / Open / Copy — treat as one path-action group | user |
| working-count-in-title | Accessor: `self._sidebar._model` per existing convention | claude |
| keyboard-cheatsheet | Manual `SHORTCUTS` table with sync comment, no introspection of QAction registry | claude |
| window-geometry-restore | `_window_to_toml` follows the existing `_ui_to_toml` pattern + `_merge_into` | claude |

## Conflict map

Files each remaining spec touches. Rows are filtered to **pending** work — the
keybinding infrastructure already touched `src/core/x11.py`, `src/core/key_grab.py`,
`src/ui/main_window.py`, and `src/ui/terminal_host.py`, so the spec entries below
are about *additional* edits on top of that landed code.

| File | Specs that touch it | Conflict risk |
|---|---|---|
| `src/ui/main_window.py` | empty-state-placeholder, keyboard-cheatsheet, row-context-path-actions, window-geometry-restore, working-count-in-title, row-jump (status-bar message only) | Low — disjoint zones (`__init__`, `closeEvent`, `_install_global_keys` bindings list, `_jump_to_row`, signal wiring), but rebase order matters |
| `src/ui/repo_sidebar.py` | row-context-path-actions, working-count-in-title, working-elapsed-time | Low — disjoint zones |
| `src/core/settings.py` | window-geometry-restore | None |

Cross-reference: **keyboard-cheatsheet must list `Ctrl+Shift+1`–`Ctrl+Shift+9`**
(the row-jump bindings), not `Alt+1`–`Alt+9`. Cheatsheet lands last so it
picks up whatever the binding table looks like at that point.

## Wave 1 — fully isolated, lowest risk

Land these first. Each touches its own corner of the codebase.

### 1. working-elapsed-time
- **Touches:** `src/ui/repo_sidebar.py` only
- **Adds:** `_turn_started: dict[str, float]`, `mark_turn_start` / `clear_turn_start`, `_format_elapsed`, tooltip-branch extension, hook wiring in `apply_hook_event`
- **Tests:** new `tests/test_repo_sidebar_working_elapsed.py`
- **Why first:** Zero overlap with anything else. Sidebar-internal.

### 2. window-geometry-restore
- **Touches:** `src/core/settings.py`, `src/ui/main_window.py` (`__init__` + `closeEvent`)
- **Adds:** `WindowState` dataclass, `_coerce_window`, `_window_to_toml`, restore-on-init with `1280x820` fallback, persist-on-close
- **Tests:** add to `tests/test_settings.py` — defaults, round-trip, comment-preserve, corrupt-blob handling
- **Why early:** Isolated to settings + two `main_window` slots that no other Wave touches.

### 3. row-context-path-actions
- **Touches:** `src/ui/repo_sidebar.py` (`_on_context_menu`, new helpers, new `path_copied = Signal(str)`), `src/ui/main_window.py` (one signal wire-up near existing sidebar wiring, new `_on_path_copied` slot)
- **Adds:** "Open in file manager" (xdg-open via `QProcess.startDetached`, `shutil.which` probe, disabled + tooltip on miss), "Copy path" (QClipboard + status-bar confirmation, middle-elide path to ~110 px)
- **No separator** before the new items
- **Tests:** new `tests/test_repo_sidebar_path_actions.py` (~5 cases)

## Wave 2 — share `main_window.py`, but in distinct slots

Rebase each on top of Wave 1 sequentially.

### 4. working-count-in-title
- **Touches:** `src/ui/repo_sidebar.py` (`working_changed = Signal()` on `RepoListModel`, emit from `set_working` after no-op guard), `src/ui/main_window.py` (`_refresh_title()`, connect signal in `__init__`, call once at init)
- **Format:** `ccwork` / `ccwork — 1 working` / `ccwork — N working`
- **Tests:** new `tests/test_main_window_title.py`

### 5. row-jump — remaining work
- **Status:** binding shipped on `Ctrl+Shift+1`..`Ctrl+Shift+9` via root-window
  XGrabKey; `MainWindow._jump_to_row(row)` slot wired and verified.
- **Remaining edits:** `src/ui/main_window.py` — extend `_jump_to_row` with the
  status-bar transient (`self.statusBar().showMessage(f"No repo at slot {row+1}", 1500)`)
  on the `row >= rowCount()` branch. Currently the slot silently no-ops.
- **Tests:** new `tests/test_alt_row_jump.py` (file name preserved for spec
  traceability even though the namespace is now Ctrl+Shift). Cover: in-range
  jump resolves to the right repo; out-of-range emits the status-bar message;
  empty sidebar is a no-op; the binding registration in `_install_global_keys`
  contains the nine `(XK_1+n, Ctrl|Shift)` tuples and not the `XK_0` slot.

### 6. empty-state-placeholder
- **Touches:** new `src/ui/empty_state.py`, `src/ui/main_window.py` (swap blank pane factory at lines ~421–424)
- **Widget:** centered logo (silent hide on SVG load failure) + heading + three hints — **`Ctrl+Shift+O` to add a repo / right-click any repo for options / `Ctrl+Shift+P` for preferences**
- **No F1 hint** — added in Wave 3 by the cheatsheet PR
- **Subhead:** full-contrast palette text
- **Tests:** new `tests/test_empty_state.py`

## Wave 3 — depends on Wave 2

### 7. keyboard-cheatsheet
- **Touches:** new `src/ui/shortcuts_dialog.py` (manual `SHORTCUTS` table with sync comment, QFormLayout per group), `src/ui/main_window.py` (add `(x11.XK_F1, 0, self._open_shortcuts)` to the `_install_global_keys` `bindings` list; add `_open_shortcuts` slot; also add the new `XK_F1` constant + the F1 keysym to `src/core/x11.py` if not already there)
- **Also:** append `Press F1 for keyboard shortcuts` line to `src/ui/empty_state.py` placeholder hints
- **Table must include** `Ctrl+Shift+1`–`Ctrl+Shift+9` (row-jump, Wave 2) and the existing infra bindings (`Ctrl+Shift+P/O/Q`, `Ctrl+Tab`/`Ctrl+Shift+Tab`, `Ctrl+=`/`Ctrl+-`/`Ctrl+0`, `Ctrl+wheel`, right-click). Source of truth is the `bindings` list in `_install_global_keys`; the sync comment names that as the authoritative table.
- **Tests:** new `tests/test_shortcuts_dialog.py` (~3 cases)
- **Docs:** optional one-line README mention

## Verification checklist (per wave)

After each spec lands:

1. `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
2. Manual smoke per `docs/specs/SMOKE-TEST.md` (currently covers the
   keybinding surface; add a section per feature as each ships)
3. Scan `CLAUDE.md` and `README.md` for stale mentions — update if drifted
4. Confirm no unrelated changes in the diff (per project guidelines)

## Out of scope (do not creep)

- No new settings UI controls for any spec (only TOML-only knobs allowed per project conventions)
- No introspection-based shortcut table for cheatsheet
- No persistence of `_turn_started` across restart
- No Wayland workarounds
- No macOS path adjustments — Linux only
- No revival of the `Alt+N` namespace for row-jump (`metaSendsEscape` makes it unworkable; `Ctrl+Shift+N` is the documented binding)
- No QAction-based shortcuts for window-level actions (the infrastructure deliberately bypasses Qt's shortcut system because it can't see xterm-focused presses)

## Open items (none blocking)

All four original ambiguity questions answered. The keybinding rework
resolved two further open questions (namespace + mechanism) that the
specs implicitly depended on. The remaining smaller decisions are
recorded in the **Resolved decisions** table above; push back on any
before Wave 1 starts.
