# Remove idle rows from the sidebar

Status: planned, not built.

## Behavior

A row that has had no activity for N days leaves the sidebar and goes to the
Recent list. A click in Recent brings it back. ccwork shows no prompt.

- Activity means a Claude hook event for the row, or a user click on the row.
  Git commits made outside ccwork do not count.
- A row with a live terminal never expires.
- The check runs at startup and once an hour.

## Settings

| Key | Type | Default |
|---|---|---|
| `ui.expire_idle_repos` | bool | off |
| `ui.expire_idle_days` | int, minimum 1 | 30 |

Preferences dialog: an **Expire idle repos** checkbox, and an **after N days**
spinbox next to it. The spinbox is disabled (greyed out) while the checkbox is off.

## Storage

`Repo.last_used: float` is an epoch timestamp, saved in `repos.json` as `last_used`.

- It is stamped on every Claude event for the row and on every click on the row.
- A repo loaded with no `last_used` gets the load time, so an upgrade expires nothing at once.
- To keep disk writes low, ccwork saves `repos.json` only when the stamp moves by
  more than an hour.

Expiry uses `RepoStore.remove_by_id`, so the `recent` rules and the badge restore
on re-add already apply.

## Tests

- A row that is older than N days, and has no live terminal, is removed and appears in `recent`.
- A row with a live terminal is kept.
- With the setting off, nothing is removed.
- A repo with no `last_used` gets the load time.
- The spinbox is disabled when the checkbox is off.

## Docs

`CLAUDE.md` (the `repo_store` section and the settings), the Preferences dialog
text, and `README.md`.
