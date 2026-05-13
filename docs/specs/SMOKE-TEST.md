# Manual smoke test — keyboard shortcuts

Verifies the root-window `XGrabKey` + `QAbstractNativeEventFilter`
shortcut surface shipped in `src/core/key_grab.py` and
`MainWindow._install_global_keys`. The mechanism is the load-bearing
piece that previous attempts kept getting wrong — it has to work from
**both** focus modes (Qt widget focus, alien xterm focus) because the
embedded xterm is not a Qt widget and Qt's normal `QAction` /
`Qt.ApplicationShortcut` path doesn't fire when xterm holds X input
focus.

```bash
# Boot with INFO logging so the dispatch line is visible if you want to
# verify a press reached the filter without watching a UI side-effect.
CCWORK_LOG=INFO ./bin/ccwork
```

Have **two** repos in the sidebar before starting (`Ctrl+Shift+O` adds
one). A couple of checks need three or more rows — noted inline.

The full bindings table is:

| Combo | Action |
|---|---|
| `Ctrl+Shift+P` | Preferences |
| `Ctrl+Shift+O` | Add Repo |
| `Ctrl+Shift+Q` | Quit |
| `Ctrl+Tab` | Next repo |
| `Ctrl+Shift+Tab` | Previous repo |
| `Ctrl+Shift+1`..`Ctrl+Shift+9` | Jump to sidebar row 1..9 |
| `Ctrl+=` / `Ctrl++` | Zoom in (xterm font) |
| `Ctrl+-` | Zoom out |
| `Ctrl+0` | Reset zoom to saved pref |
| Ctrl + scroll-wheel | Zoom in/out (per-terminal) |
| Right-click on terminal | Context menu |

---

## 0. Startup

- [ ] App launches without an error dialog.
- [ ] Log contains `global keys: 18 shortcuts on root=0x...` (one line,
  registration succeeded). If absent, no shortcut works — investigate
  `_install_global_keys`.
- [ ] No `KeyGrabFilter.register: replacing handler` warnings (would
  indicate a duplicate binding).

---

## 1. Sidebar focus  ⚠ baseline

Click an empty area of the sidebar list first so a Qt widget owns
keyboard focus.

- [ ] `Ctrl+Shift+P` opens Preferences. Close it (Esc / Cancel).
- [ ] `Ctrl+Shift+O` opens the Add-Repo file picker. Cancel.
- [ ] `Ctrl+Tab` cycles selection forward through repos. With ≥3 rows,
  the wrap-around past the last row lands back on the first.
- [ ] `Ctrl+Shift+Tab` cycles backward. Wraps the other way.
- [ ] `Ctrl+Shift+1` selects row 1. `Ctrl+Shift+2` selects row 2.
- [ ] `Ctrl+Shift+9` with fewer than 9 rows: nothing happens (no
  error, no jump). The dispatch fires but `_jump_to_row` short-circuits
  on out-of-range.
- [ ] `Ctrl+Shift+0` does **nothing**. It's intentionally unbound
  (reserved for a possible future "last row" / "10th row" binding).
- [ ] `Ctrl+Shift+Q` quits cleanly (with a confirm prompt only if a
  Claude turn is in flight).

---

## 2. xterm focus  ⚠ load-bearing

The case the previous attempts got wrong. Click into a repo's terminal
first; type a few characters at the shell prompt to confirm xterm owns
keyboard input. **Do not press Enter** — leave the line edited so you
can spot whether a shortcut accidentally got typed into it.

- [ ] `Ctrl+Shift+P` opens Preferences. The xterm shell line shows
  **no extra characters**. Close the dialog.
- [ ] `Ctrl+Shift+O` opens the Add-Repo file picker. **No bash
  *operate-and-get-next* effect** (the shell line where your cursor was
  must not have been executed). Cancel.
- [ ] `Ctrl+Tab` cycles to the next repo even though xterm holds X
  focus. (This was the original regression — the old hand-rolled
  `cycle_repo_requested` signal route only fired when xterm focus
  routed through Qt, which XEmbed prevents.)
- [ ] `Ctrl+Shift+3` (with ≥3 rows) jumps to row 3 and focuses that
  repo's terminal. **No `^[`, `ESC`, or digit leaks** appear at the
  previous shell prompt. If anything leaks, the grab regressed or a
  modifier-state mask is wrong.
- [ ] Press `Ctrl+=` (or `Ctrl++`). xterm font grows by one point.
  Status bar shows `Font size: N pt`.
- [ ] Press `Ctrl+-`. Font shrinks by one point.
- [ ] Press `Ctrl+0`. Font snaps back to the on-disk saved value.
- [ ] Hold Ctrl, scroll the mouse wheel up/down over the terminal.
  Font zooms in/out matching the key behavior.
- [ ] Right-click on the terminal. Context menu appears with Paste,
  Reload terminal, Preferences…
- [ ] `Ctrl+Shift+Q` quits cleanly.

---

## 3. Pass-through — what ccwork must NOT consume

These bindings collide with bash readline, the tty driver, and Claude
itself; if any of them suddenly start triggering ccwork actions, the
keybinding namespace has slipped.

With xterm focused:

- [ ] Plain `Ctrl+P` walks readline history backward (or fires Claude's
  prompt action). ccwork does **not** open Preferences.
- [ ] Plain `Ctrl+O` triggers readline's *operate-and-get-next*. ccwork
  does **not** open Add-Repo.
- [ ] Plain `Ctrl+Q` is consumed by the tty driver (XON). ccwork does
  **not** quit.
- [ ] Plain `Alt+1` through `Alt+9` either reaches xterm as
  `ESC+digit` (default `metaSendsEscape`) or is swallowed by the WM —
  ccwork does **not** jump rows. (Our row-jump is `Ctrl+Shift+digit`,
  not `Alt+digit`.)

If any of these accidentally fire ccwork, look at
`MainWindow._install_global_keys` — a binding was added without
Shift+Ctrl scoping.

---

## 4. Cleanup teardown

- [ ] After quit, no orphaned `xterm` processes
  (`pgrep -fa 'xterm.*-into'` returns nothing).
- [ ] No leaked X grabs: re-launch ccwork. The new instance logs
  `global keys: 18 shortcuts on root=0x...` again with no
  `KeyGrabFilter.register: replacing handler` warning (a prior
  instance's grabs would not be visible to a new instance, but a
  hung-but-alive prior ccwork would block its grabs — `pgrep -f
  'python -m src.main'` should be empty before relaunch).

---

## 5. working-elapsed-time

**What changed:** the working-row tooltip now ends with `Working {elapsed}`
while a Claude turn is in flight, so the spinner reads as an analog
gauge instead of a binary alive-or-hung indicator.

- [ ] In a sidebar repo's terminal, run `claude` and submit a prompt that
  will take a while (`"count from 1 to 30 with 1s pauses"` or similar).
- [ ] Spinner appears on the row.
- [ ] **Hover** the row. After ~3 seconds, mouse off, mouse back on.
  Tooltip third line reads `Working {N}s`.
- [ ] Wait ~70 seconds. Hover again — tooltip reads `Working 1m {S}s`.
- [ ] Press `Esc` to interrupt the turn, then submit a new prompt.
  Hover again — the seconds count should have **reset to zero**, not
  carried over from the interrupted turn.
- [ ] Let the turn finish (`Stop` event). Hover — tooltip is the
  `Claude finished a turn / {path}` two-line shape, **no `Working` line**.

---

## 6. window-geometry-restore

**What changed:** ccwork remembers window size, position, and maximize
state across launches. The first-launch fallback is still 1280×820.

- [ ] Drag the window to a non-default position (or to a secondary
  monitor).
- [ ] Resize to a distinct non-default size (e.g. very tall and narrow).
- [ ] Quit via `Ctrl+Shift+Q`.
- [ ] Relaunch. Window comes up at the same size and position.
- [ ] Maximize. Quit. Relaunch. Window comes up maximized.
- [ ] Un-maximize (saved blob still records the maximize flag). Drag to
  a third position. Quit. Relaunch. Window comes up at the new dragged
  position, not maximized.

**Corruption fallback:** *(corrupt blob path; log-only by design)*

- [ ] Quit ccwork. Edit `~/.config/ccwork/settings.toml` and set
  `geometry = "not-valid-base64!!!"` under `[window]`.
- [ ] Relaunch with `CCWORK_LOG=INFO ./bin/ccwork`.
- [ ] Window opens at the 1280×820 default. Console logs
  `corrupt window.geometry blob (...) — using default` at WARNING.
- [ ] **No status-bar message, no modal dialog** — this is intentional
  per the user's "not THAT loud" feedback; the log line is the only
  surface.
- [ ] Quit. The corrupt blob is overwritten with a fresh valid one.

---

## 7. row-context-path-actions

**What changed:** the sidebar row right-click menu has two new items —
*Open in file manager* and *Copy path* — between *Clone this repo* and
the badge group.

- [ ] Right-click any sidebar repo. Menu order top-to-bottom:
  **Reload terminal**, **Clone this repo**, **Open in file manager**,
  **Copy path**, ────, **Set badge…**, **Clear badge**, ────,
  **Remove from sidebar**. **No separator** between *Clone this repo*
  and *Open in file manager* (they read as one path-action cluster).

**Copy path:**

- [ ] Click *Copy path*.
- [ ] Status bar shows `Copied: {path}` (middle-elided if long) for
  ~2 seconds.
- [ ] Paste somewhere (text editor, address bar). The full absolute
  path is on the clipboard, untouched.
- [ ] Add (or rename) a repo whose path contains a space. *Copy path*
  still works; the space survives end-to-end.

**Open in file manager:**

- [ ] Click *Open in file manager*.
- [ ] Your desktop's default file manager opens at the repo directory.
- [ ] (Optional) Temporarily mask xdg-open
  (`sudo mv /usr/bin/xdg-open /usr/bin/xdg-open.bak`). Right-click a
  repo. *Open in file manager* is **disabled** and its tooltip mentions
  `xdg-utils`. Restore xdg-open after testing.

---

## 8. working-count-in-title

**What changed:** the window title gains a `— N working` suffix while
any repo has a Claude turn in flight. Visible from alt-tab switchers,
taskbars, and tiling-WM bars even without ccwork being focused.

- [ ] Title bar reads `ccwork` while idle.
- [ ] Start a Claude turn in repo A. Title: `ccwork — 1 working`.
- [ ] Start another turn in repo B (don't wait for A to finish). Title:
  `ccwork — 2 working`.
- [ ] Wait for one to finish (or `Esc` to abort + new prompt to reset
  the elapsed timer). Title drops by one.
- [ ] After both finish, title is back to `ccwork`.
- [ ] Alt-tab to another window. The taskbar / window switcher shows
  the ` — N working` count without ccwork being focused.
- [ ] (Optional, with a duplicate row) `Ctrl+Shift+O` the same repo
  twice so you have two rows on the same path. Start a turn — title
  says `1 working`, not `2`. (Path-keyed count.)

---

## 9. row-jump empty-slot feedback

**What changed:** pressing `Ctrl+Shift+N` for a slot that doesn't have
a repo now flashes a transient status-bar message instead of silently
no-op'ing.

- [ ] With fewer than 9 rows in the sidebar, press `Ctrl+Shift+9`.
  Bottom-of-window status bar reads `No repo at slot 9` for ~1.5 s.
  No jump, no error.
- [ ] Try `Ctrl+Shift+1` on an empty sidebar (no repos added yet).
  Status bar reads `No repo at slot 1`.
- [ ] In-range slots still jump silently (no extra status message for
  the success path).

---

## 10. empty-state-placeholder

**What changed:** the right pane shown when no terminal is current is
no longer a flat gray rectangle — it's a centered ccwork logo +
heading + version subhead + three keyboard hints.

**Cold-start path:**

- [ ] Quit ccwork. Move `~/.config/ccwork/repos.json` aside
  (`mv ~/.config/ccwork/repos.json{,.bak}`). Relaunch.
- [ ] The right pane shows: logo / `ccwork` heading / `v{version} —
  embedded xterm sessions for Claude Code` subhead / three hint lines:
  - `Press Ctrl+Shift+O to add a repo`
  - `Right-click any repo for options`
  - `Press Ctrl+Shift+P for preferences`
- [ ] Logo image is visible (the `logo/v2-icon.svg` glyph).
- [ ] Resize the window very narrow. Layout doesn't blow up — text
  word-wraps, content stays centered.
- [ ] Restore `repos.json`: `mv ~/.config/ccwork/repos.json{.bak,}`.
  Quit & relaunch.

**Terminal-exited path:**

- [ ] Open a repo's terminal. In the xterm, type `exit` and press
  Enter to kill the shell.
- [ ] The xterm closes. The right pane drops back to the same
  placeholder widget (logo + heading + hints).

**Logo-missing fallback:**

- [ ] Quit. Temporarily rename `logo/v2-icon.svg` (`mv logo/v2-icon.svg
  logo/v2-icon.svg.bak`). Relaunch with no repos.
- [ ] Placeholder still renders heading + version + 3 hints. Logo
  label is silently hidden (no broken-image glyph).
- [ ] Restore the SVG (`mv logo/v2-icon.svg.bak logo/v2-icon.svg`) and
  relaunch.

---

## Synthetic verification (optional)

For CI-style regression checks without a human pressing keys, the script
at `/tmp/ccwork_keytest.py` (or wherever you parked it; not committed)
uses `libXtst`'s `XTestFakeKeyEvent` to inject the five canonical combos
(`Ctrl+Shift+P/O`, `Ctrl+Tab`, `Ctrl+Shift+Tab`, `Ctrl+Shift+1`) and
parses the log for `KeyGrabFilter DISPATCH` lines plus `wmctrl -l` for
dialog appearance. It's not a replacement for the load-bearing
xterm-focus checks above — XTest reproduces the X-server-side path
faithfully but doesn't exercise xterm's PTY echo, which is what
catches escape-sequence leaks.

If any **⚠ load-bearing** item regresses, file an issue before tagging
a release.
