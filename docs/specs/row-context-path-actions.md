# Row context menu: path actions

Add **Open in file manager** and **Copy path** to the sidebar row right-click
menu.

## Motivation

Every list-of-paths UI a developer touches — IDE project trees, Finder /
Nautilus, GitHub Desktop, GitKraken, Sublime Merge — exposes "reveal in
file manager" and "copy absolute path" at one right-click. They cost
nothing to keep in muscle memory and a noticeable amount of friction to
work around when absent (open a terminal, `pwd`, select, copy). ccwork's
sidebar is a list of paths; users will expect both.

## Scope

**In:**

- One new menu item: *Open in file manager*. Spawns the user's default
  file manager pointing at `repo.path`.
- One new menu item: *Copy path*. Puts `repo.path` on the clipboard.
- Status-bar confirmation for *Copy path* (no toast, no dialog).

**Out:**

- No preferences. No way to choose a different file manager, no way to
  customize the copy format (no "copy as URI", no "copy relative path").
- No keyboard shortcuts on the row (the menu is the surface).
- No new Repo fields, no new settings keys.

## Design

### Menu placement

Insert both items as a new group between *Clone this repo* and the
existing `addSeparator()` that precedes *Set badge…* in
`RepoSidebar._on_context_menu` (`src/ui/repo_sidebar.py:1228`). The
existing structure is already grouped by concern:

1. Terminal actions: *Reload terminal*
2. Repo actions: *Clone this repo* ← add path actions immediately after
3. Cosmetic: *Set badge…*, *Clear badge*
4. Destructive: *Remove from sidebar*

*Open in file manager* and *Copy path* operate on the path itself, which
puts them in the same conceptual bucket as *Clone this repo* (which also
keys off `repo.path`). Adding a separator between *Clone this repo* and
*Open in file manager* is optional; recommended **no separator** so the
three path-y items read as one group, and the existing separator before
*Set badge…* still cleanly fences the cosmetic items off.

Final order:

```
Reload terminal
Clone this repo
Open in file manager
Copy path
─────────────
Set badge…
Clear badge
─────────────
Remove from sidebar
```

### Open in file manager

Use **`xdg-open <path>` via `QProcess.startDetached("xdg-open", [path])`**.

Why not `QDesktopServices.openUrl(QUrl.fromLocalFile(path))`: it has
historically been flaky across desktops — on some KDE/Plasma builds it
launches Dolphin with the path as a *selection target* rather than as
the directory to open, and on minimal X11 sessions without a registered
default handler it silently no-ops. `xdg-open` is a thinner contract:
"hand the URL to the desktop's opener and exit." It is part of
`xdg-utils`, which is a dependency of essentially every desktop meta-
package on Debian, Fedora, Arch, openSUSE.

Use `QProcess.startDetached` (same call already used for the system
emoji picker at `src/ui/repo_sidebar.py:1306`) — fire-and-forget, no
zombie, returns a bool.

**Missing `xdg-open`**: probe once at menu-build time via
`shutil.which("xdg-open")`. If absent, **disable** the action and set a
tooltip explaining why ("`xdg-open` not found. Install the `xdg-utils`
package."). Disabling (vs. showing a `QMessageBox` on click) follows
the precedent set by *Browse system…* in the badge dialog when no
system emoji picker is found, and avoids a modal dialog for an
environmental problem the user can't fix from inside ccwork. Log at
`WARNING` when the probe fails so it shows up under `CCWORK_LOG=DEBUG`.

If `startDetached` itself returns `False` (xdg-open present but launch
failed — rare), log at `WARNING` and surface a one-shot
`statusBar().showMessage("Could not open file manager", 3000)`.

### Copy path

```python
from PySide6.QtGui import QGuiApplication
QGuiApplication.clipboard().setText(repo.path)
```

Confirmation: `MainWindow.statusBar().showMessage(f"Copied: {elided}", 2000)`.
The sidebar doesn't own a status bar — emit a new signal
`path_copied = Signal(str)` from `RepoSidebar` and let `MainWindow` wire
it to its existing `statusBar()` in `_wire_sidebar` (mirroring the
`reload_requested` / `repo_removed` pattern already used). Keep the
elision in `MainWindow` so the sidebar stays display-agnostic.

Elision: `QFontMetrics(self.statusBar().font()).elidedText(path,
Qt.ElideMiddle, self.statusBar().width() - 80)`. Middle-elide is the
right call for paths — preserves both the repo basename and the
top-level dir.

## Files touched

- `src/ui/repo_sidebar.py` — add two `QAction`s in `_on_context_menu`;
  add a `path_copied = Signal(str)` class attribute; add a
  `_open_in_file_manager(repo)` helper and a `_copy_path(repo)` helper.
- `src/ui/main_window.py` — connect `sidebar.path_copied` to a new
  `_on_path_copied(path)` slot that elides and calls `showMessage`.
- `tests/test_repo_sidebar_path_actions.py` — new file. See *Tests*.

No changes to `src/core/`. No new settings.

## Edge cases

- **Paths with spaces / special chars.** `QProcess.startDetached` passes
  argv elements directly to `execvp`; no shell, no quoting hazard. Same
  for `QGuiApplication.clipboard().setText` — it's a raw string. No
  action required, but the test suite should include one path with a
  space to keep this guarantee from regressing.
- **Broken symlink / deleted directory.** `repo.path` is stored at
  add-time and never re-validated. If the directory has since been
  removed, `xdg-open` will fail; the file manager itself will surface
  the error (Nautilus shows "Sorry, could not display all the contents
  of …"). We do not pre-`os.path.isdir` check — that would be a
  TOCTOU race anyway, and the file-manager error message is more
  informative than anything we could produce.
- **Missing `xdg-utils`.** Covered above (probe + disable + tooltip).
- **Very long paths in the status message.** Middle-elide to fit the
  status bar's current width.
- **Wayland clipboard quirks.** Qt's `QClipboard` handles Wayland's
  data-offer model transparently — the surface is the same as X11.
  ccwork forces `QT_QPA_PLATFORM=xcb` anyway (`src/main.py`), so we're
  on XFIXES regardless, but the code should not assume that — leave it
  as a plain `setText` call.
- **Multiple rapid copies.** `statusBar().showMessage` with a timeout
  auto-cancels the previous message; no queue management needed.

## Tests

New file `tests/test_repo_sidebar_path_actions.py`:

1. **`test_copy_path_puts_path_on_clipboard`** — build a `RepoSidebar`
   with one repo, call the `_copy_path` helper directly (no need to
   exercise the menu), assert `QGuiApplication.clipboard().text() ==
   repo.path`. Runs under `QT_QPA_PLATFORM=offscreen`.
2. **`test_copy_path_emits_signal`** — connect a `QSignalSpy` to
   `path_copied`, call `_copy_path`, assert one emission carrying
   `repo.path`.
3. **`test_copy_path_handles_spaces`** — same as #1 but with a path
   containing a space, to lock in the no-quoting-needed guarantee.
4. **`test_open_in_file_manager_invokes_xdg_open`** — monkeypatch
   `QProcess.startDetached` with a recorder lambda, call
   `_open_in_file_manager`, assert it was called as
   `("xdg-open", [repo.path])`.
5. **`test_open_in_file_manager_disabled_when_xdg_open_missing`** —
   monkeypatch `shutil.which` to return `None`, build the context
   menu (refactor a small `_build_context_menu(repo) -> QMenu` helper
   so this is testable without `QTest.mouseClick`), assert the
   *Open in file manager* action's `isEnabled()` is `False` and its
   tooltip mentions `xdg-utils`.

Follow the `qapp` fixture pattern from
`tests/test_preferences_dialog.py` for `QApplication` setup.

## Out of scope

- **Open in editor** (`$EDITOR`, `code .`, etc.) — separate spec.
  Conflates with terminal-spawned editor behavior, deserves its own
  design pass for editor detection and per-repo override.
- **Per-OS launchers** — macOS `open`, Windows `explorer.exe`.
  ccwork is Linux+X11 only for v0.1
  (see `docs/roadmap-cross-platform.md`); cross-platform launcher
  selection lands when the rest of the cross-platform work does.
- **"Copy as `file://` URI"** / **"Copy relative to home"** — possible
  future submenu, but YAGNI for v0.1. Single-line *Copy path* covers
  the 95% case.
