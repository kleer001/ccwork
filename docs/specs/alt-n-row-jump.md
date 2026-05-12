# Alt+N row jump

Direct keyboard jump to sidebar row N (1-indexed) via `Alt+1` … `Alt+9`.

## Motivation

Once a user keeps more than five repos in the sidebar, `Ctrl+Tab` cycling
turns into a counting exercise — to reach the seventh repo you press
`Ctrl+Tab` six times, mentally tracking position. Every other
multi-pane tool the audience uses solves this with digit shortcuts:
VSCode (`Ctrl+1..9` for editor groups), Firefox / Chrome (`Ctrl+1..8`
for tabs, `Ctrl+9` for last tab), tmux (`prefix 0..9` for windows),
Slack (`Ctrl+1..9` for workspaces), iTerm2 (`Cmd+1..9`). Adding direct
jump keys closes the gap between "I can see which repo I want" and
"my cursor is in its terminal" from `O(N)` keystrokes to one.

## Scope

In:

- `Alt+1` … `Alt+9` jump the sidebar selection to the 1st … 9th visible
  row, focus that repo's xterm. Same code path as a mouse click on the
  row, so terminal spawn / title bar / last-focused-stripe behavior is
  inherited for free.
- Works while the xterm has X input focus (the dominant case), not only
  when Qt-side widgets have focus.
- Out-of-range presses (fewer than N rows) are silent no-ops aside from
  a short status-bar hint.

Out:

- `Alt+0` is intentionally unbound. We reserve it for a possible future
  "last row" or "10th row" binding; mapping it now and changing it later
  would break muscle memory.
- No chord prefix (no `Ctrl+K 3`); no per-user remapping in
  Preferences. If a user objects to the keybinding the answer is "edit
  `src/ui/main_window.py`" — same as for `Ctrl+Tab` today.
- No multi-window / multi-instance scope; ccwork is single-window.

## Design

### Where the bindings live

The existing `MainWindow._install_shortcuts()` already registers
window-level `QAction`s with `Qt.ApplicationShortcut`. That is the
**necessary but not sufficient** half of the wiring (see "Edge cases"
below for the X11 grab half). Extend the loop in `_install_shortcuts`
with nine more actions:

```
for n in range(1, 10):
    act = QAction(f"Jump to repo {n}", self)
    act.setShortcut(QKeySequence(f"Alt+{n}"))
    act.setShortcutContext(Qt.ApplicationShortcut)
    act.triggered.connect(lambda _=False, row=n - 1: self._jump_to_row(row))
    self.addAction(act)
```

`row=n-1` binds the 0-indexed row at lambda creation time — the usual
Python late-binding gotcha.

### Slot: row N → repo

Add `MainWindow._jump_to_row(row: int)`:

1. `model = self._sidebar.model`
2. If `row >= model.rowCount()`, show a transient hint
   (`self.statusBar().showMessage(f"No repo at slot {row+1}", 1500)`)
   and return.
3. `repo = model.repo_at(row)` — None-guard against a TOCTOU race with
   row removal.
4. `self._select_repo(repo)` (existing helper — calls
   `self._sidebar.select_id(repo.id)`, which fires
   `repo_selected` → `_on_repo_selected` → spawn/swap terminal and
   focus xterm).

This deliberately reuses `_select_repo` instead of touching the model
directly so the click and key paths produce identical state.

### Visible row vs. insertion order

"Row N" means **the row currently at visual position N**. With
auto-arrange and active-grouping both on (the default-friendly path),
the topmost rows are the recently-active and currently-running repos —
exactly what the user wants `Alt+1` to land on. The sidebar model is
already authoritative for visual order: `RepoListModel.repo_at(row)`
returns rows in the same order `QListView` paints them, so no extra
plumbing is needed.

This composes correctly with mid-animation reorder
(`_step_arrange`): the bubble walk mutates the model in place, so a
`Alt+3` press lands on whatever row 3 holds *at the moment the slot
runs*, which is what the user can see.

## Files touched

- `src/ui/main_window.py` — extend `_install_shortcuts()` to register
  the nine `QAction`s; add `_jump_to_row(row: int)` slot. ~15 lines net.
- `src/ui/terminal_host.py` — add the nine `Alt+digit` combos to
  `_install_zoom_grabs()` / `_uninstall_zoom_grabs()` so xterm doesn't
  swallow them (see Edge cases). Forward them as accepted no-ops in
  `keyPressEvent` — the `Qt.ApplicationShortcut` action fires on its
  own once the grab routes the keypress into Qt.
- `src/core/x11.py` — add `XK_1` … `XK_9` keysym constants
  (`0x0031` … `0x0039`) and `Mod1Mask = 1 << 3` (the X11 modifier bit
  for Alt on standard layouts).
- `tests/test_alt_row_jump.py` — new file (see Tests).

No settings, no Preferences UI, no migration.

## Edge cases

### Empty sidebar / fewer than N rows

`_jump_to_row` short-circuits with a 1.5 s status-bar message
`"No repo at slot N"`. No modal, no sound. Mirrors how VSCode silently
ignores `Ctrl+9` when fewer than nine editors are open (we surface a
hint because the status bar is otherwise unused and it costs one line).

### xterm eating Alt as Meta (the load-bearing risk)

xterm's default `metaSendsEscape: true` resource means
**Alt+digit produces `ESC` followed by the digit on the PTY** —
readline reads this as `M-1`, `M-2` etc. In a vanilla xterm under
ccwork that's exactly what would happen and the Qt shortcut would
never fire, because xterm holds X input focus and the `Alt+1` press
is delivered straight to it.

`Qt.ApplicationShortcut` alone does **not** rescue this. It's the
right scope to make Qt willing to fire the action regardless of which
Qt widget has Qt-side focus, but the embedded xterm is **not a Qt
widget** — it's an alien X window XEmbed'd into our hierarchy.
`Ctrl+Tab` already works only because `TerminalHost._install_zoom_grabs`
calls `XGrabKey` on the xterm's container, which makes the X server
deliver matching `KeyPress` events to *us* before xterm sees them.
Drop the grab and `Ctrl+Tab` would type a literal tab into the
shell.

**Therefore Alt+digit must be grabbed the same way.** Implementation:

1. In `src/core/x11.py`, add `Mod1Mask = 1 << 3` and `XK_1`…`XK_9`.
2. In `TerminalHost._install_zoom_grabs`, loop `for ks in
   (x11.XK_1, …, x11.XK_9): self._xdisplay.grab_key(wid, ks,
   x11.Mod1Mask)`. The existing `_LOCK_VARIANTS` fan-out in
   `x11.XDisplay.grab_key` covers NumLock/CapsLock automatically.
3. Mirror in `_uninstall_zoom_grabs`.
4. In `TerminalHost.keyPressEvent`, when
   `event.modifiers() & Qt.AltModifier` and `Qt.Key_1 <= key <=
   Qt.Key_9`, just `event.accept()` and `return` — let the
   `Qt.ApplicationShortcut` `QAction` on `MainWindow` fire. (Qt
   delivers the key to the focused widget first; accepting it
   prevents propagation to the X xterm child, but the shortcut layer
   still gets to evaluate the matched sequence — same model as
   `Ctrl+Tab` today.)

Confirm with a manual test: press `Alt+1` with the xterm focused; the
sidebar should jump to row 1 and **no `ESC1` should appear at the
shell prompt**. If `ESC1` does appear, the grab regressed.

### Fallback if the grab proves unreliable on some WM/keymap combo

Should the Alt+digit grab fail on an exotic layout (e.g. a keyboard
where digits are Mode_switch'd), the cheap fallback is **`Ctrl+1` …
`Ctrl+9`** — `ControlMask` is already used by zoom and Tab grabs and
is known to work end-to-end. Cost: `Ctrl+1`..`Ctrl+9` collides with
some shell readline bindings (`Ctrl+1` is rarely bound, but users
remap freely). Recommendation: ship Alt+digit first, downgrade to
Ctrl+digit only if a real user reports the keystroke not reaching Qt.

### Interaction with `Alt+F4`, `Alt+Tab`, etc.

These are window-manager-level grabs that run **above** ccwork's
passive grab. The WM consumes them before X delivers them anywhere,
so there's no conflict — `Alt+Tab` keeps switching windows, ccwork
never sees the press.

### Active-grouping or auto-arrange off

`repo_at(row)` returns whatever order the model is in. If the user has
both off, "row 3" is the third row in insertion order, which is also
what they see. No special-casing needed.

## Tests

New file `tests/test_alt_row_jump.py`, following the `qapp` fixture
pattern from `tests/test_preferences_dialog.py`. Cover:

1. **Slot resolves visible-row to the right repo.** Build a
   `RepoListModel` with four repos at `/a`, `/b`, `/c`, `/d`. Call
   `model.apply_auto_arrange()` after stamping activity so the order
   is `[d, c, b, a]`. Construct a `MainWindow`-like harness (or
   directly test `_jump_to_row` if we extract it; alternatively spy
   on `RepoSidebar.select_id`). Assert `_jump_to_row(0)` selects the
   repo at `/d`.
2. **Out-of-range is a silent no-op.** Three repos, `_jump_to_row(5)`.
   Assert no `select_id` call, no exception, status-bar message
   non-empty.
3. **Empty sidebar is a no-op.** Zero repos, `_jump_to_row(0)`. No
   exception, no `select_id`.
4. **Alt+0 is not bound.** Inspect `MainWindow.actions()` and assert
   no action has shortcut `QKeySequence("Alt+0")`. This is a
   regression guard for the "reserved for later" promise.
5. **Action shortcut context is `ApplicationShortcut`.** For each of
   the nine actions, `act.shortcutContext() == Qt.ApplicationShortcut`.

X11 grab behavior is not unit-testable under `offscreen` (no xterm,
no real keyboard). Verification of the grab itself is manual, on the
release smoke-test checklist:

- Add `[ ] Alt+1..Alt+9 jumps the sidebar to row N while the xterm is
  focused; no escape sequence appears at the shell prompt.` to
  `docs/release-checklist.md` under "Fresh-machine smoke test".

## Out of scope

- **`Alt+0`.** Reserved. Don't bind it in this change.
- **User-remappable bindings.** Same posture as `Ctrl+Tab` / `Ctrl+,`
  today — config-as-code.
- **Multi-window jumps.** ccwork has one window.
- **A "go to row" command palette / fuzzy picker.** Different feature,
  different design.
- **Number-overlay HUD à la vimium.** Out of taste scope; the row
  ordering is already visible.
