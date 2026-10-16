# Route hook events to the terminal's row

Status: planned, not built.

## Goal

Each hook event changes only the row whose terminal sent it. Two rows on one
path show independent spinners and badges.

When a row's terminal starts Claude in a different git repo, that row is
renamed in place to the new repo.

## Design

### Row id in the environment

1. `src/core/terminal_session.py` `build_session` sets `CCWORK_ROW_ID=<repo.id>`
   next to `CCWORK_GUI=1`.
2. `bin/ccwork-hook-sink` adds `"row":"$CCWORK_ROW_ID"` to every event line.
3. `bin/claude` adds `"row"` to its `RepoAdded` line.

### Routing rules (`MainWindow._on_hook_event`)

| Event state | Action |
|---|---|
| `row` missing or empty | Drop the event. Log a warning with the event name and `cwd`. |
| `row` not in the store | Drop the event. Log a warning. |
| `RepoAdded` with a `row` | Ignore it. The automatic rebind (below) covers this case. |
| `RepoAdded` with no `row` | Keep the current behavior: add a row when no row has that path. |
| Any other event | Apply the event to that row only. |

There is no fallback to path routing.

### Automatic rebind

On `SessionStart`, ccwork finds the git root of the session's `cwd`
(`git rev-parse --show-toplevel`).

| Case | Result |
|---|---|
| The git root is the row's path | No change. |
| The `cwd` is a subdirectory of the row's repo | No change, because the git root is the same. |
| The `cwd` is not in a git repo | No change. |
| The git root is a different repo | Rebind the row to that git root. |

A rebind keeps the row id, the terminal, the emoji and the title. ccwork shows
no prompt.

`RepoStore.rebind(repo_id, new_path)` is new, and both the automatic rebind and
the manual *Rebind to…* menu action use it:

- It sets the Roman-numeral instance for the new path with the same rules as `add`.
- It resets the old path's last survivor to instance 0.
- It pushes the old path to `recent` when the old path has no rows left.
- It drops the new path from `recent`.

`RepoListModel.rebind_repo` calls `RepoStore.rebind` and refreshes both paths.
A rebind can move the row in the sort. The move uses the existing quiet-gated
bubble walk.

### Model state keyed by row id

`src/ui/repo_model.py` keys these dicts by repo id, not by path: `_status`,
`_working`, `_turn_started`, `_subagents`, `_session_active`, `_live_sessions`,
`_last_activity`, `_session_ended`.

- `apply_hook_event(event, repo_id, payload)` takes a repo id.
- `clear_session(repo_id)` takes a repo id.
- The `RepoSidebar` wrappers take repo ids.
- The branch cache and the path-missing cache stay keyed by path.

### MainWindow

- `_on_terminal_finished` clears only the row of the terminal that exited.
  The check for "a duplicate terminal on this path is still alive" goes away.
- `_refresh_title` and the quit confirmation count working rows, not distinct paths.
- `session_recovery` stays keyed by `cwd`, because `claude --resume` must run in
  the session's own directory.

## Tests

- An event with a row id changes that row only. A duplicate row on the same path
  does not change.
- An event with a missing row id, or an unknown one, is dropped and logs a warning.
- A `SessionStart` from another git root rebinds the row: same id, new path,
  correct instance numbers on both paths, and correct `recent` entries.
- A `SessionStart` in a subdirectory, or in a directory outside git, does not rebind.
- A `RepoAdded` with a row id adds no row.
- `_on_terminal_finished` clears only its own row.
- Replace the path-normalization tests in `tests/test_repo_sidebar_working.py`.

Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q`. Name the
`tests` directory, because a plain `pytest` also collects the clones under `tmp/`.

Live check: open two rows on one path, run Claude in one, and confirm that only
that row animates. Then `cd` to another repo, start Claude, and confirm that the
row renames.

## Docs

`CLAUDE.md`: the Event flow section, the "Terminals are keyed by `repo.id`"
convention, the `repo_store` section, and the `bin/` section. Also `README.md`.
