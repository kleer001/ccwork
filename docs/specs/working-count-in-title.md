# Working-count in window title

Show the number of repos with an in-flight Claude turn in the window title,
so the count is visible from alt-tab switchers, taskbars, and tiling-WM bars
without the window being focused.

---

## 1. Motivation

ccwork's bell dot in the top bar announces "something happened" (a `Stop` or
`Notification` event), but it doesn't answer "is Claude still busy?". When
the window is minimized, hidden behind a browser, or tucked into a tiling-WM
workspace, even the bell is invisible. A title-bar suffix solves the same
problem Gmail's `(3) Inbox` and Slack's `(2) Slack` titles solve: glanceable
state in the one surface every window manager already renders. The data is
already in `RepoListModel._working`; we just need to expose its size.

## 2. Scope

**In:**

- A live counter in the window title derived from `model.working_paths()`.
- Title updates on every working-state transition (hook event or terminal
  exit clearing).

**Out:**

- Naming the working repos in the title.
- Attention-state counts. A future extension could surface
  `ccwork — 2 working, 1 needs attention`; v1 ships the working count only.
- System-tray unread badge integration (separate spec).
- A Preferences toggle to disable the suffix or customize its format.

## 3. Design

### Format

```
ccwork                       # count == 0
ccwork — 1 working           # count == 1
ccwork — N working           # count >= 2
```

Em dash (U+2014, surrounded by single spaces). Singular `working` reads
fine at N=1; we keep it as a fixed-noun suffix rather than pluralizing
("1 working" not "1 working repo") because it composes cleanly with later
suffixes — `ccwork — 2 working, 1 needs attention` is the obvious next
step, and `ccwork — 2 repos working, 1 repo needs attention` is noisier.

The em-dash trailing form was picked over the email-convention parenthetical
prefix `(N) ccwork` for the same forward-composability reason: a prefix
counter doesn't have an obvious slot for the second clause, while the
trailing form just grows. The cost is that the app name no longer sorts
first character-wise in WM lists, which we accept.

### Update trigger

`RepoListModel.set_working` already emits `dataChanged` for `ROLE_WORKING`
on the affected row(s). Two options for hooking the title:

- **(a)** Connect to `RepoListModel.dataChanged` and filter on
  `ROLE_WORKING in roles`. Works, but couples the title refresh to per-row
  signals — every duplicate-row broadcast triggers a re-check, and we have
  to inspect the `roles` list every time.
- **(b)** Add a new `working_changed = Signal()` on `RepoListModel`, emitted
  from inside `set_working` only on the actual True↔False edge (after the
  `if working == was: return` guard that already exists at
  `src/ui/repo_sidebar.py:335`).

**Recommend (b).** Cheaper to hook (no role filtering), decoupled from
row-level paint signals, and `_on_terminal_finished` already routes its
cleanup through `set_working(path, False)` (at
`src/ui/main_window.py:522`), so terminal-exit clearing Just Works without
a second wiring point.

### Where to compute

Add `MainWindow._refresh_title(self)` that reads
`len(self._sidebar._model.working_paths())` and calls `setWindowTitle`.
Connect the new signal to it in `__init__`, alongside the existing
`hook_server.event_received` wiring (`src/ui/main_window.py:148`). Call
it once at the end of `__init__` so the title is correct on first paint
(count is 0, so this is a no-op visually but makes the invariant explicit).

The sidebar already exposes the model as `self._sidebar._model`; if a
public accessor is preferred, add `RepoSidebar.model()` rather than
reaching into the private attr. Either is acceptable; the existing code
base already reads `self._sidebar._model` from `MainWindow` (e.g. around
the working-id derivation near `src/ui/main_window.py:588`), so the
convention is "private access is fine within ui/".

### Path-keyed counting

`_working` is a `set[str]` of normalized paths (`src/ui/repo_sidebar.py:183`),
so duplicate rows on the same path count **once**, matching `any_working()`
and the existing path-broadcast semantics of `set_working`. This is the
right call: the count answers "how many distinct repos is Claude working
in" rather than "how many sidebar rows are spinning", and a user with two
duplicate rows on `~/code/foo` running one Claude session would expect to
see `1 working`, not `2`. Per-session counting is future work and depends
on the same per-session routing that's already flagged as future work in
`CLAUDE.md` ("Terminals are keyed by `repo.id`, not `repo.path`").

Document this in the docstring on `_refresh_title` and in a one-line
comment next to the `setWindowTitle` call.

## 4. Files touched

- `src/ui/repo_sidebar.py` — declare `working_changed = Signal()` on
  `RepoListModel`; emit it from `set_working` after the
  `if working == was: return` guard, after `_emit_changed_for_path`.
- `src/ui/main_window.py` — add `_refresh_title`; connect
  `self._sidebar._model.working_changed` to it in `__init__`; call once at
  the end of `__init__`. Replace the literal `self.setWindowTitle("ccwork")`
  at line 69 with the initial state-aware call (or leave the literal and
  let the explicit `_refresh_title()` call at end-of-`__init__` overwrite —
  fine either way, the no-suffix case is just `"ccwork"`).

No new modules, no settings changes, no migration.

## 5. Edge cases

- **Terminal exits while working.** Already handled at
  `src/ui/main_window.py:506`: `_on_terminal_finished` calls
  `set_working(path, False)` if no other terminal at the path is alive.
  With option (b), that path emits `working_changed` and the title
  decrements without any extra wiring.
- **Rapid event bursts.** A burst of `UserPromptSubmit` events across N
  repos in the same tick fires N signals and N title updates.
  `setWindowTitle` is cheap (a property setter and a WM round trip on
  change); no coalescing required. Do **not** wrap in `processEvents` or
  add a debounce — the WM-level rate limiting is sufficient at
  human-perceptible event rates, and a debounce would lag the indicator
  behind the spinner, which is the more authoritative signal at row level.
- **Window-modal dialogs.** Qt's `QMessageBox` and `QDialog` set their own
  titles for the dialog window; they do **not** mutate the parent
  `QMainWindow` title. The Preferences dialog is constructed with `self`
  as parent (see existing usage) and likewise does not touch our title.
  No-op for v1; if a future contributor introduces a dialog that mutates
  the parent title, that's their problem to push the suffix through.
- **Self-healing of stuck working state.** If a Claude turn crashes
  without firing `Stop`, the repo's working flag stays True until the next
  `UserPromptSubmit` (which is a no-op for the flag but refreshes the
  timestamp) or until the user kills the terminal. The title will reflect
  this — a stuck count is the right surface to expose it on, arguably
  better than today where only the spinner glyph hints at it.

## 6. Tests

Add `tests/test_main_window_title.py`. Reuse the `qapp` fixture pattern
from `tests/test_preferences_dialog.py:23`. Construct `MainWindow` with
an in-memory `RepoStore` (a few `Repo`s) and a real `HookServer` (or a
stub — the title plumbing doesn't need a live socket; calling
`sidebar.apply_hook_event(event, path)` directly is sufficient).

Cover:

1. `windowTitle() == "ccwork"` immediately after construction with no
   working repos.
2. After `apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/path/a")`:
   `windowTitle() == "ccwork — 1 working"`.
3. After a second `UPS` on `/path/b`: `"ccwork — 2 working"`.
4. After `EVENT_STOP` on `/path/a`: back to `"ccwork — 1 working"`.
5. After `EVENT_STOP` on `/path/b`: back to `"ccwork"`.
6. **Duplicates count once.** Two `Repo` rows with the same `path` and
   different `id`. `apply_hook_event(UPS, path)` raises the count to 1,
   not 2. A second `UPS` on the same path is a no-op for the title.
7. `EVENT_NOTIFICATION` does **not** change the title (working flag is
   untouched per `apply_hook_event` contract).
8. **Signal fires once per edge.** Connect a `QSignalSpy` (or a counter
   slot) to `working_changed` and assert no spurious emissions on
   repeat-`set_working(path, True)` after the path is already working.

## 7. Out of scope

- Attention-state count in the title (separate extension; the format
  reserves space for it as `ccwork — N working, M needs attention`).
- Per-repo names in the title (`ccwork — foo, bar working`). Loses
  glanceability fast at N > 2 and re-raises the truncation question that
  the sidebar already solves better.
- System-tray icon / unread badge (separate spec; different surface,
  different platform constraints).
- Preferences toggle to disable or reformat the suffix. If users object,
  add one in a follow-up; defaulting to "always on" matches the spirit
  of the bell dot and the desktop-notification path.
