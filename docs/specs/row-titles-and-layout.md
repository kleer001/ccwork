# Row titles and the three-line row

Status: planned, not built. Needs `docs/specs/row-routing.md` (the row id).

## Row layout

Every row has three lines. Row height is the same for all rows.

```
┌───────────────────────────┐
│🌱 fix login bug         ● │   line 1: emoji + title (bold)
│   garden | main           │   line 2: repo name (+ Roman suffix) | branch
│   Needs permission        │   line 3: status text
└───────────────────────────┘
```

| Line | Content | When it is empty |
|---|---|---|
| 1 | The emoji and the title | No title is set. The line stays blank. |
| 2 | `name (II) \| branch`, or `(detached)` / `(path missing)` in place of the branch | Never |
| 3 | The status text (below) | No session, or the status-text preference is off |

When line 2 is too narrow, the branch elides first, then the name.

### Status text (line 3)

| State | Text |
|---|---|
| A badge shows | The badge's word from `docs/specs/hook-events.md` |
| Working, no badge | `Working · 2m`, the time since the turn started |
| Session open and idle | `Claude open` |
| Bare shell, or no terminal | Empty |

The elapsed time comes from `_turn_started`. It updates on the existing spinner
timer tick.

Preference: **Show status text** (`ui.show_status_text`, default on). When it is
off, line 3 stays blank and the row keeps its height.

`LayoutSettings.row_height` gets a new default for three lines.

## Title

`Repo.title: str = ""` is saved in `repos.json` as `title`.

- The title is per row id, like the emoji.
- The `recent` list does not keep the title.
- `display_name` does not change.
- `ROLE_TITLE` is a new model role.

### Sync with Claude's session title

The row title and the Claude Code session title are the same value.

| Direction | Mechanism |
|---|---|
| Claude to row | `SessionStart` and `UserPromptSubmit` payloads carry `session_title` when a custom title is set (`/rename`, `--name`, or a hook's `sessionTitle`). When the payload title is different from the row title, ccwork sets the row title. A payload with no `session_title` does not clear the row title. |
| Row to Claude | ccwork writes each row's title to `$XDG_RUNTIME_DIR/ccwork/titles/<row id>`. On `SessionStart` and `UserPromptSubmit`, `bin/ccwork-hook-sink` reads that file. When the file is different from `session_title`, the sink prints `{"hookSpecificOutput":{"hookEventName":"<event>","sessionTitle":"<title>"}}`. |

On `SessionStart`, `sessionTitle` applies only when `source` is `startup`,
`resume` or `fork`.

Claude's auto-generated titles are not custom titles, so they do not reach ccwork.
ccwork sees a `/rename` only at the next prompt or session start.

### Set the title or emoji from a session

`bin/ccwork-rename [--badge <emoji>] "<title>"` sends
`{"event":"RowRenamed","row":"$CCWORK_ROW_ID","title":"…","emoji":"…"}` to the
socket. It uses the same JSON escape and socat or nc path as `bin/claude`.

- An empty title clears the title.
- With no `--badge`, the emoji does not change. `--badge ""` clears the emoji.
- The command exits 1 with a message when `CCWORK_GUI` or `CCWORK_ROW_ID` is not set.

`MainWindow._on_hook_event` handles `RowRenamed` beside `RepoAdded`:

1. It finds the row with `store.find_by_id`.
2. It sets the title and the emoji, then calls `store.save()`.
3. It writes the title file and emits `dataChanged` for that row.

An unknown row id follows the drop-and-warn rule in `docs/specs/row-routing.md`.

To tell Claude that the command exists, the sink adds `additionalContext` to its
`SessionStart` output: "You run in a ccwork sidebar row. When the task is clear,
run `ccwork-rename \"<short topic>\"`. Add `--badge <emoji>` to set the row icon."

### Edit the title from the sidebar

The context menu gets **Set title…**, a text dialog that shows the current
title. An empty value clears the title. **Clear title** shows only when a title
is set.

The session and the user write the same `Repo.title`. The last write wins.

## Tests

- The title round-trips through `repos.json`. The `recent` list drops it.
- The delegate paints three lines with a title, without a title, and with the
  status text off.
- Status text: the badge word, `Working · Nm`, `Claude open`, and empty.
- `RowRenamed`: title only, title and emoji, an empty title, and an unknown row id.
- The sink's `SessionStart` and `UserPromptSubmit` output when the title file is
  different from `session_title`, and no output when they are the same.
- An incoming `session_title` updates the row.

Live check: open two rows on one path. Run `/rename` in one session, send a
prompt, and confirm that only that row's title changes. Then set a title from
the sidebar, send a prompt, and confirm that Claude's title follows.

## Docs

`CLAUDE.md` (the UI layer, the `repo_store` section, the `bin/` section), the
Preferences dialog text, and `README.md`.
