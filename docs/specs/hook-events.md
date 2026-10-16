# More hook events, and a badge for each way Claude stops

Status: planned, not built. Needs `docs/specs/row-routing.md` (the row id).
Reference: https://code.claude.com/docs/en/hooks.md

## Badge table

The colors are solarized colors from `badge_theme`. The word is the tooltip
text and the line-3 status text.

| Trigger | Word | Color | Rank |
|---|---|---|---|
| PermissionRequest, Notification `permission_prompt` | Needs permission | red | 1 |
| Notification `elicitation_dialog`, `elicitation_url_dialog` | Needs an answer | orange | 2 |
| StopFailure `rate_limit` | Rate limited | magenta | 3 |
| StopFailure `overloaded`, `server_error` | API overloaded | magenta | 3 |
| StopFailure `authentication_failed`, `billing_error`, `account_on_hold`, `oauth_org_not_allowed`, `cloud_credential_error` | Account problem | magenta | 3 |
| StopFailure `max_output_tokens` | Output limit hit | magenta | 3 |
| StopFailure `invalid_request`, `model_not_found`, `unknown` | API error | magenta | 3 |
| Notification `quota_auto_resume_stale` | Usage limit: press Enter | yellow | 4 |
| Notification `quota_auto_resume_disabled` | Usage limit reached | yellow | 4 |
| PreCompact | Compacting (auto or manual) | violet, own glyph | while it runs |
| Stop | Done | green | 5 |

These Notification types show no badge: `idle_prompt`, `auth_success`,
`agent_needs_input`, `agent_completed`. The types `elicitation_complete`,
`elicitation_response` and `quota_auto_resume_fired` also show no badge, but
they clear a badge (see the next table).

When two badges apply, the lower rank number wins.

## When each badge clears

| Badge | Clears on |
|---|---|
| Needs permission | Stop, StopFailure, the next prompt, or the session end |
| Needs an answer | Notification `elicitation_complete` or `elicitation_response`, Stop, StopFailure, or the next prompt |
| API errors (rank 3) | The next prompt, or the session end |
| Usage limit | Notification `quota_auto_resume_fired`, the next prompt, or the session end |
| Compacting | PostCompact, Stop, StopFailure, the next prompt, or the session end |
| Done | The next prompt, or the session end |

`StopFailure` runs instead of `Stop`, so a turn never gets both an error and Done.

## Hook changes in `install.sh`

| Hook | Change |
|---|---|
| `StopFailure` | New. It sets the error badge from the `error` field. It also sends a desktop notification, under the same `desktop_notifications` gate as Stop and Notification. |
| `Notification` | Keep matcher `"*"`. The model maps `notification_type` with the table above. Today, every type sets ATTENTION. |
| `PermissionRequest` | New. It sets the red badge at once, and it records `tool_name` and a short summary of `tool_input` for the tooltip, for example `Bash: rm -rf build`. It never returns a decision. |
| `SubagentStart` | New. It replaces `PreToolUse` with matcher `Task`. The model keeps a set of live `agent_id`s per row. `SubagentStop` removes the same `agent_id`. A resumed subagent fires `SubagentStart` again, and the set ignores the repeat. |
| `PreToolUse` | Removed. |
| `PreCompact`, `PostCompact` | New. They drive the compaction glyph. |
| `PostToolUse`, `PostToolUseFailure` | Not installed. Each tool call would start a process. |
| `PermissionDenied` | Not installed. It fires only on automatic denials, never on a manual "No". |

Re-running `install.sh` is the upgrade path, because the installer strips the old
ccwork hooks before it writes the new set.

## Model changes

- `_status` holds one of: `DONE`, `PERMISSION`, `ANSWER`, `ERROR` (with its
  word), `USAGE_LIMIT` (with its word), or nothing. `STATUS_ATTENTION` splits
  into `PERMISSION` and `ANSWER`.
- `_compacting` is a new per-row flag with its own role. The compaction glyph is
  in the outboard slot, below ranks 1 to 4 and above the working spinner.
- `_subagents` changes from a counter to a set of `agent_id`s.
- `_pending_tool` is new per-row text from `PermissionRequest`. It clears with
  the permission badge.
- The new glyphs, colors and words go in `badge_theme.py`, so
  `~/.config/ccwork/badges.toml` can override them.

## Permission badge timing

The red badge lights on `PermissionRequest`, which fires as soon as Claude asks.
The `permission_prompt` Notification fires only after the prompt has waited about
six seconds. It also sets the badge, which covers a prompt that has no
`PermissionRequest`, such as a sandboxed command's network request.

## Tests

- PermissionRequest sets the red badge and the pending-tool text.
- Each row of the badge table sets the correct status and word.
- Each row of the clear table clears its badge.
- The ignored Notification types change nothing.
- A SubagentStart and SubagentStop pair, a repeated SubagentStart, and a
  SubagentStop with an unknown id.
- PreCompact sets the flag. PostCompact or Stop clears it.

## Docs

`CLAUDE.md`: the Event flow section, the event table, the outboard-slot priority
list, and the Install section. Also `README.md`.
