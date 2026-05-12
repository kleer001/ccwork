# Keyboard shortcuts cheatsheet

Status: design spec, not implemented.

## 1. Motivation

ccwork has no menu bar, no Help surface, and no in-app documentation. New
users discover Ctrl+, only because the gear button advertises it in a
tooltip, and discover Ctrl+Tab / Ctrl+= / Ctrl+Shift+V only by reading
`CLAUDE.md` or `terminal_host.py`. Tooltips only cover the buttons the
user happens to hover. A single keystroke that lists every shortcut —
the convention every editor and IDE follows — closes that gap with
roughly one screen of UI and zero ongoing maintenance cost beyond
"append one line when a shortcut is added."

## 2. Scope

**In:**

- A modal `QDialog` ("Keyboard shortcuts") that lists every keyboard
  shortcut ccwork exposes, grouped by context (Window, Sidebar,
  Terminal).
- Two trigger keys (`F1` and `?`) plus future-proofing for a Help
  menu / button.
- Static, scrollable, read-only presentation.

**Out:**

- Rebinding (deferred — see Out of scope).
- Search / filter box.
- Printable export, copy-to-clipboard of the whole table.
- Context-sensitive popovers (e.g. "press F1 inside the terminal to see
  only terminal shortcuts").

## 3. Design

### Trigger

Register two new window-level `QAction`s alongside the existing three
in `MainWindow._install_shortcuts`:

```python
("Keyboard shortcuts", QKeySequence("F1"), self._open_shortcuts),
("Keyboard shortcuts", QKeySequence("?"), self._open_shortcuts),
```

Two `QAction`s with the same slot is the idiomatic way to bind two
sequences to one command in Qt (a single `QAction` supports only one
primary sequence cleanly across platforms). Both use
`Qt.ApplicationShortcut` so they fire whether the sidebar or a
terminal has focus — important because the user reaches for `F1`
mid-task.

Note that `?` is `Shift+/` on a US keyboard. Qt's `QKeySequence("?")`
handles that correctly. On layouts where `?` requires AltGr or a dead
key, the binding may silently fail to register — acceptable, since
`F1` is the documented primary trigger and `?` is a convenience.

### Help button — recommend *skip*

Two options: (1) add a `?` `QToolButton` next to the gear, or (2) rely
on F1 alone. Recommend **(2)**: the top bar is already dense (title,
alerts toggle, bell, gear) and a fifth glyph erodes the centered-title
illusion. Pure-keystroke Help is consistent with Add Repo / Quit, which
also have no button. If a Help menu ever materializes, route it at the
same `_open_shortcuts` slot; no dialog change required.

### Dialog widget

New file `src/ui/shortcuts_dialog.py` exposing
`ShortcutsDialog(QDialog)`. Layout:

- `QVBoxLayout` containing one `QGroupBox` per context (Window,
  Sidebar, Terminal), each wrapping a two-column `QFormLayout`.
- `QFormLayout` rows pair `QLabel("Action description")` (left) with
  `QLabel("<keystroke>")` (right). Right label uses a fixed-width
  font (`QFontDatabase.systemFont(QFontDatabase.FixedFont)`) so
  multi-key sequences align visually.
- Wrap the groupboxes in a `QScrollArea` so the dialog stays usable
  at small window heights.
- Close button row at the bottom: `QDialogButtonBox(QDialogButtonBox.Close)`.
- `setWindowTitle("Keyboard shortcuts")`, `setModal(True)`,
  `resize(480, 520)` as a starting size.

Use `QFormLayout` rather than `QTableWidget`: QTableWidget brings
selection/header/grid behavior we'd then have to suppress, and the
rows-per-group structure is more naturally expressed as a sequence
of forms inside group boxes.

### Data source

A single module-level constant in `shortcuts_dialog.py`:

```python
SHORTCUTS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Window", [
        ("Preferences",          "Ctrl+,"),
        ("Add repo",             "Ctrl+O"),
        ("Quit",                 "Ctrl+Q"),
        ("Keyboard shortcuts",   "F1  /  ?"),
    ]),
    ("Sidebar", [
        # (none today — sidebar inherits Window shortcuts)
    ]),
    ("Terminal", [
        ("Zoom in",              "Ctrl+=  /  Ctrl++"),
        ("Zoom out",             "Ctrl+-"),
        ("Reset zoom",           "Ctrl+0"),
        ("Zoom (mouse)",         "Ctrl+scroll"),
        ("Next repo",            "Ctrl+Tab"),
        ("Previous repo",        "Ctrl+Shift+Tab"),
        ("Copy selection",       "Ctrl+Shift+C  (xterm)"),
        ("Paste",                "Ctrl+Shift+V"),
        ("Context menu",         "Right-click"),
    ]),
]
```

**Manual table vs. derive-from-QAction.** A derived list would
auto-sync with `_install_shortcuts`, but only covers the three Window
shortcuts — every terminal shortcut lives in `TerminalHost`'s
X11-grabbed-keysym table and is not a `QAction` at all, and the
xterm-owned `Ctrl+Shift+C` has no Qt representation whatsoever.
Deriving half the list and hand-writing the other half is worse than
hand-writing all of it.

Recommendation for v1: manual table, with a comment at the top of
`shortcuts_dialog.py`:

```
# When adding a shortcut, update SHORTCUTS below AND the relevant
# binding site (MainWindow._install_shortcuts for window-level,
# TerminalHost._ZOOM_KEYS / _install_zoom_grabs / keyPressEvent for
# terminal-level).
```

The test (section 6) will catch most drift in practice.

### Current shortcut inventory

Extracted from `src/ui/main_window.py` and `src/ui/terminal_host.py`
on the date of this spec. Use as the canonical seed for `SHORTCUTS`.

| Context  | Action               | Keystroke              | Bound where                                         | Notes                              |
|----------|----------------------|------------------------|-----------------------------------------------------|------------------------------------|
| Window   | Preferences          | `Ctrl+,`               | `main_window.py:176` `_install_shortcuts`           | Qt `QAction`                       |
| Window   | Add repo             | `Ctrl+O`               | `main_window.py:177` `_install_shortcuts`           | Qt `QAction`                       |
| Window   | Quit                 | `Ctrl+Q`               | `main_window.py:178` `_install_shortcuts`           | `QKeySequence.Quit` (platform std) |
| Terminal | Zoom in              | `Ctrl+=` or `Ctrl++`   | `terminal_host.py:264` `_ZOOM_KEYS`, `keyPressEvent`| X11 grab + Qt fallback             |
| Terminal | Zoom out             | `Ctrl+-`               | `terminal_host.py:264` `_ZOOM_KEYS`, `keyPressEvent`| X11 grab + Qt fallback             |
| Terminal | Reset zoom           | `Ctrl+0`               | `terminal_host.py:264` `_ZOOM_KEYS`, `keyPressEvent`| Re-reads on-disk pref              |
| Terminal | Zoom (mouse wheel)   | `Ctrl+scroll`          | `terminal_host.py:333` `wheelEvent`                 | X11 grab on Button4/Button5        |
| Terminal | Next repo            | `Ctrl+Tab`             | `terminal_host.py:285` `_install_zoom_grabs`        | Wraps around                       |
| Terminal | Previous repo        | `Ctrl+Shift+Tab`       | `terminal_host.py:286` `_install_zoom_grabs`        | Qt delivers as `Key_Backtab`       |
| Terminal | Copy selection       | `Ctrl+Shift+C`         | xterm itself (not ccwork)                           | See Edge cases                     |
| Terminal | Paste                | `Ctrl+Shift+V`         | xterm itself (not ccwork)                           | Also a context-menu entry          |
| Terminal | Context menu         | Right-click            | `terminal_host.py:288` `_install_zoom_grabs`        | Plain Button3, no modifier         |

## 4. Files touched

- **`src/ui/shortcuts_dialog.py`** *(new)* — `ShortcutsDialog(QDialog)`
  class plus the `SHORTCUTS` module-level table.
- **`src/ui/main_window.py`** — import `ShortcutsDialog`; add two
  `QAction`s in `_install_shortcuts` (F1, `?`); add a thin
  `_open_shortcuts(self)` slot that does
  `ShortcutsDialog(self).exec()`.
- **`tests/test_shortcuts_dialog.py`** *(new)* — see section 6.
- **`README.md`** *(optional, recommended)* — one sentence under
  Preferences: "Press F1 to see the full keyboard shortcut list."
  No table duplication — the dialog is the source of truth.

No changes to settings, repo store, or hook flow.

## 5. Edge cases

- **xterm-owned shortcuts.** `Ctrl+Shift+C` (copy) and `Ctrl+Shift+V`
  (paste) are interpreted by xterm itself; ccwork never sees the
  keystrokes. They belong in the cheatsheet because users perceive
  them as ccwork shortcuts. Label the copy row clearly — e.g.
  `Ctrl+Shift+C  (xterm)` — so a future contributor isn't confused
  when grepping for the keysym and finding nothing in our codebase.
  Paste is also available via the right-click context menu; the
  dialog row can stay un-annotated since both paths land at the
  same outcome.
- **Right-click as a "shortcut".** It's listed because it opens the
  context menu, which is itself a shortcut surface. Worth one row.
- **Platform-specific bindings.** None today. `QKeySequence.Quit`
  resolves to `Ctrl+Q` on Linux and `Cmd+Q` on macOS, but ccwork is
  Linux-only (see `docs/roadmap-cross-platform.md`), so the cheatsheet
  can hard-code `Ctrl+Q` for v1. If a future platform widens the
  surface, change the relevant row to read from `QKeySequence::Quit`
  via `QKeySequence(QKeySequence.Quit).toString(QKeySequence.NativeText)`
  and accept that the table now mixes literal strings with derived
  ones.
- **`?` on non-US layouts.** As noted under Trigger, the secondary
  binding may not register. F1 is the documented primary; do not
  alert the user if `?` fails to bind.
- **Dialog opened twice.** `exec()` is modal; a second F1 while the
  dialog is up is swallowed by Qt. No special handling needed.

## 6. Tests

New `tests/test_shortcuts_dialog.py`, reusing the `qapp` fixture
pattern from `tests/test_preferences_dialog.py`
(`QT_QPA_PLATFORM=offscreen` set at import time, session-scoped
`QApplication.instance() or QApplication([])`). Three tests:

- **`test_shortcuts_table_has_expected_groups`** — assert "Window" and
  "Terminal" are present in `[g for g, _ in SHORTCUTS]`.
- **`test_shortcuts_table_covers_known_bindings`** — flatten the table
  and assert each of `Ctrl+,`, `Ctrl+O`, `Ctrl+Q`, `Ctrl+Tab`,
  `Ctrl+Shift+V` appears in at least one row. Catches an accidental
  delete-the-table refactor.
- **`test_dialog_instantiates_and_lists_entries`** — instantiate
  `ShortcutsDialog()`, assert `windowTitle() == "Keyboard shortcuts"`
  and `sum(len(rows) for _, rows in SHORTCUTS) >= 10`. Call
  `dlg.deleteLater()` in a `finally` to keep the offscreen platform
  tidy.

No need to test the F1/`?` binding itself — `QAction` + `addAction` is
Qt's territory, and `test_preferences_dialog.py` doesn't test its own
Ctrl+, binding either.

## 7. Out of scope

- **Rebinding.** Needs a persisted shortcut table in `Settings`,
  conflict detection, a capture widget, plus rework of the X11-grab
  bindings in `TerminalHost` (they aren't `QAction`s and can't be
  rebound without re-grabbing). Defer until requested.
- **Search / filter.** With ~10 entries, scanning beats searching;
  revisit past ~30.
- **Printable / clipboard export.** Add only on request.
- **Context-sensitive popovers** ("F1 here = terminal-only list").
- **Help menu.** If a menu bar ever returns, point its "Keyboard
  shortcuts…" entry at the same `_open_shortcuts` slot.
