# Working elapsed time

Surface how long a repo has been "working" (since the most recent
`UserPromptSubmit`) in the row tooltip, so the spinner reads as an
analog gauge instead of a binary "still alive?" indicator.

## Motivation

The braille spinner says a turn is in flight, but every spinning row
looks identical — ten seconds in and ten minutes in are
indistinguishable, which is exactly when the user starts to wonder "is
Claude actually doing something, or did it hang?" Long turns are a
real pain point. Elapsed time turns the spinner from a binary into an
analog gauge without changing its existing semantics.

## Scope

In: stamp a per-path turn-start timestamp on `UserPromptSubmit`, clear
on `Stop`, append `Working 27s` to the tooltip when a row is working
and has a recorded start.

Out: per-turn history (only the current turn matters), inter-turn
averages, alerts on long turns, inline elapsed text in the badge column
(see Design — explicitly deferred), persistence across ccwork restarts.

## Design

### Storage

Add one field to `RepoListModel.__init__` next to the other per-path
dicts (`src/ui/repo_sidebar.py:193`):

```python
# Per-path monotonic timestamp of the most recent UserPromptSubmit.
# Set on UPS, cleared on Stop. Distinct from _last_activity (which
# also stamps on Stop and Notification) — we need *turn began*.
self._turn_started: dict[str, float] = {}
```

Keyed by un-normalized `path`, matching `_status` and `_last_activity`.
(`_working` is the odd one out — keyed by normalized path. Don't reuse
it.)

### Mutators

Two new methods on `RepoListModel`:

```python
def mark_turn_start(self, path: str) -> None:
    self._turn_started[path] = time.monotonic()

def clear_turn_start(self, path: str) -> None:
    self._turn_started.pop(path, None)
```

Wire into `apply_hook_event` (`src/ui/repo_sidebar.py:354`):

- `EVENT_USER_PROMPT_SUBMIT`: call `mark_turn_start(path)` alongside
  the existing `clear_status` / `set_working` / `touch_activity`.
- `EVENT_STOP`: call `clear_turn_start(path)` alongside the existing
  `set_working(False)` / `set_status(DONE)`.
- `EVENT_NOTIFICATION`: untouched — turn is still live, start time
  still valid.

### Self-healing on interrupted turns

If `UserPromptSubmit` arrives while `_working` is already True (the
case `touch_activity` was explicitly added for), `mark_turn_start`
**overwrites** the prior timestamp. That's correct: the previous turn
was abandoned (Esc-interrupted, crash, …), the new prompt should
count from zero. No special-casing — dict assignment does it.

### Tooltip

Extend the `Qt.ToolTipRole` branch in `RepoListModel.data`
(`src/ui/repo_sidebar.py:224`). Current shape is at most two lines
(`{label}\n{repo.path}`); for working rows with a recorded start,
append a third:

```
Claude is working…
{repo.path}
Working 27s
```

Helper:

```python
def _format_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    h, rem = divmod(s, 3600)
    return f"{h}h {rem // 60}m"
```

Bare seconds under a minute; `1m 23s` up to an hour; `1h 5m` thereafter
(seconds dropped in the hours bucket — multi-hour turns are pathological
and second-precision stops being useful).

Tooltip branch:

```python
if _norm(repo.path) in self._working:
    started = self._turn_started.get(repo.path)
    if started is not None:
        elapsed = _format_elapsed(time.monotonic() - started)
        return f"{WORKING_LABEL}\n{repo.path}\nWorking {elapsed}"
    return f"{WORKING_LABEL}\n{repo.path}"
```

The `started is None` fallback covers "ccwork started mid-turn" — see
Edge cases.

### Inline display (deferred)

Painting elapsed text next to the spinner glyph in the badge column
was considered and rejected for v1. The column is sized for a single
glyph; `27s` or `1m 23s` would overflow at narrow widths (splitter
floor 60 px) or force the column to widen dynamically, complicating
the delegate's `_is_group_boundary` and sizeHint math. The tooltip
handles the curiosity case well enough; revisit if a future signal
suggests hover isn't discoverable.

### Refresh cadence

Qt tooltips are queried on hover-show but **not** refreshed while
visible — `QToolTip` is a single static widget. Rely on re-show on the
next hover; a one-second stale read is not a user-visible problem.
Programmatic refresh via the existing `_spinner_timer` is possible but
rejected as overkill for a "seconds digit updates while you watch"
payoff nobody asked for.

## Files touched

- `src/ui/repo_sidebar.py` — `_turn_started` field, `mark_turn_start` /
  `clear_turn_start` mutators, `_format_elapsed` helper, two new calls
  in `apply_hook_event`, two new lines in the `ToolTipRole` branch.
  Net ~25 lines.
- `tests/test_repo_sidebar_working_elapsed.py` — new file (see Tests).

No settings, no Preferences UI, no migration.

## Edge cases

- **UPS while working already True.** `mark_turn_start` overwrites; the
  tooltip reads `Working 0s` and counts up. Correct.
- **Stop with no preceding UPS.** `clear_turn_start` is `pop(..., None)`
  — no-op, no exception.
- **Clock changes mid-turn.** `time.monotonic()` is immune to wall-clock
  adjustment. Use it consistently for both the stamp and the elapsed
  calculation; never mix in `time.time()`.
- **ccwork restart mid-turn.** Nothing persisted; on restart no
  `_turn_started` entry exists, the tooltip falls through to the
  two-line shape. The next `Stop` no-op-clears. Accepted — monotonic
  timestamps can't survive a process restart anyway.
- **Duplicate Repos on the same path.** Storage is path-keyed, the
  tooltip runs per-row, every duplicate shows the same elapsed time.
  Matches `_working` and `_status` behavior.
- **Symlinked `cwd`.** Same posture as `_last_activity` — keyed by the
  un-normalized `repo.path` that `MainWindow._on_hook_event` forwards
  to `apply_hook_event`. Keys agree.

## Tests

New file `tests/test_repo_sidebar_working_elapsed.py`. Mirror the
`qapp` / `_store_with` fixtures from
`tests/test_repo_sidebar_working.py` and monkeypatch
`src.ui.repo_sidebar.time.monotonic` to control the stamp/read clock.
Cover:

1. **UPS stamps a turn start.** Monkeypatch monotonic to `T0`, fire
   `apply_hook_event(EVENT_USER_PROMPT_SUBMIT, "/a")`; assert
   `model._turn_started["/a"] == T0`.
2. **Tooltip elapsed format.** UPS at `T0`, advance clock and assert
   the `Qt.ToolTipRole` suffix for each band: `+27` → `Working 27s`;
   `+83` → `Working 1m 23s`; `+3725` → `Working 1h 2m`.
3. **Stop clears the turn start.** UPS, then `EVENT_STOP`. Assert
   `"/a" not in model._turn_started` and the post-Stop tooltip is the
   `STATUS_DONE` shape with no `Working …` line.
4. **Interrupted turn resets the timer.** UPS at `T0`, advance to
   `T0 + 30`, fire UPS again; assert `_turn_started["/a"] == T0 + 30`.
5. **Working True without UPS.** `set_working("/a", True)` directly;
   tooltip stays at the two-line shape, no `KeyError`.
6. **`_format_elapsed` unit table.** `0 → "0s"`, `59 → "59s"`,
   `60 → "1m 0s"`, `3599 → "59m 59s"`, `3600 → "1h 0m"`. Pure function.

X11 / xterm / hover-rendering is not exercised — the tooltip string is
what the model owns.

## Out of scope

- Inline elapsed text in the row (deferred per Design).
- Per-turn history.
- "Turn took 47s" notification on Stop.
- Configurable long-turn alert thresholds.
- Persisting turn start across ccwork restarts.
