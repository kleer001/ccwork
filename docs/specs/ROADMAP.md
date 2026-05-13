# Specs Roadmap

Implementation plan for the seven specs in `docs/specs/`. All seven are rated
**Small** difficulty. The bottleneck is `src/ui/main_window.py` (touched by 6
of 7), but the edits land in disjoint zones (`_install_shortcuts`,
`__init__`, `closeEvent`, terminal lifecycle, signal wiring). Sequencing
matters more than parallelism for a solo dev — order below is chosen to keep
each PR self-contained and to land the cross-referencing specs last.

## Resolved decisions

| Spec | Decision | Source |
|---|---|---|
| alt-n-row-jump | Empty-slot feedback: status-bar `"No repo at slot N"`, 1.5 s transient | user |
| empty-state-placeholder | Logo fallback: **silently hide image**, keep heading + hints | user |
| empty-state-placeholder | **No F1 hint in Wave 2** — cheatsheet PR (Wave 3) appends it | user |
| empty-state-placeholder | Subhead: full-contrast palette text (simpler; both options OK per spec) | claude |
| row-context-path-actions | **No separator** between Clone / Open / Copy — treat as one path-action group | user |
| working-count-in-title | Accessor: `self._sidebar._model` per existing convention | claude |
| keyboard-cheatsheet | Manual `SHORTCUTS` table with sync comment, no introspection of QAction registry | claude |
| window-geometry-restore | `_window_to_toml` follows the existing `_ui_to_toml` pattern + `_merge_into` | claude |

## Conflict map

| File | Specs that touch it | Conflict risk |
|---|---|---|
| `src/ui/main_window.py` | alt-n-row-jump, empty-state-placeholder, keyboard-cheatsheet, row-context-path-actions, window-geometry-restore, working-count-in-title | Low — disjoint zones, but rebase order matters |
| `src/ui/repo_sidebar.py` | row-context-path-actions, working-count-in-title, working-elapsed-time | Low — disjoint zones |
| `src/core/settings.py` | window-geometry-restore | None |
| `src/core/x11.py` | alt-n-row-jump | None |
| `src/ui/terminal_host.py` | alt-n-row-jump | None |

Cross-reference: **keyboard-cheatsheet must list Alt+1–9** if alt-n-row-jump
has shipped. Cheatsheet lands last.

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

### 5. alt-n-row-jump
- **Touches:** `src/ui/main_window.py` (extend `_install_shortcuts`, add `_jump_to_row(row)` slot), `src/ui/terminal_host.py` (Alt+digit grabs in `_install_zoom_grabs` / `_uninstall_zoom_grabs`, accept Alt+digit in `keyPressEvent`), `src/core/x11.py` (add `Mod1Mask = 1 << 3`, `XK_1`..`XK_9`)
- **Empty slot:** status-bar message `"No repo at slot N"`, 1.5 s transient
- **Tests:** new `tests/test_alt_row_jump.py`

### 6. empty-state-placeholder
- **Touches:** new `src/ui/empty_state.py`, `src/ui/main_window.py` (swap blank pane factory at lines ~421–424)
- **Widget:** centered logo (silent hide on SVG load failure) + heading + three hints (Ctrl+O / right-click / Ctrl+,)
- **No F1 hint** — added in Wave 3 by the cheatsheet PR
- **Subhead:** full-contrast palette text
- **Tests:** new `tests/test_empty_state.py`

## Wave 3 — depends on Wave 2

### 7. keyboard-cheatsheet
- **Touches:** new `src/ui/shortcuts_dialog.py` (manual `SHORTCUTS` table with sync comment, QFormLayout per group), `src/ui/main_window.py` (F1 + `?` actions in `_install_shortcuts`, `_open_shortcuts` slot)
- **Also:** append `Press F1 for keyboard shortcuts` line to `src/ui/empty_state.py` placeholder hints
- **Table must include** Alt+1–9 from Wave 2.5
- **Tests:** new `tests/test_shortcuts_dialog.py` (~3 cases)
- **Docs:** optional one-line README mention

## Verification checklist (per wave)

After each spec lands:

1. `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
2. Manual smoke: `./bin/ccwork`, exercise the new feature
3. Scan `CLAUDE.md` and `README.md` for stale mentions — update if drifted
4. Confirm no unrelated changes in the diff (per project guidelines)

## Out of scope (do not creep)

- No new settings UI controls for any spec (only TOML-only knobs allowed per project conventions)
- No introspection-based shortcut table for cheatsheet
- No persistence of `_turn_started` across restart
- No Wayland workarounds
- No macOS path adjustments — Linux only

## Open items (none blocking)

All four ambiguity questions answered. The remaining smaller decisions are
recorded in the **Resolved decisions** table above; push back on any before
Wave 1 starts.
