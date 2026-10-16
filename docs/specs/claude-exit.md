# Detect when `claude` exits

Status: planned, not built. Needs `docs/specs/row-routing.md` (the row id).

## Problem

Claude Code sends no `SessionEnd` hook for the `/exit` slash command
(anthropics/claude-code#17885). ccwork clears session state only when the
row's xterm exits. After an `/exit`, the shell stays open and the row keeps a
stale session state.

## Design

1. `bin/claude` runs the real binary as a child process, not with `exec`. It
   keeps the exit code and returns it.
2. After the child exits, `bin/claude` sends
   `{"event":"ClaudeExited","row":"$CCWORK_ROW_ID","cwd":"…","code":N}` to the socket.
3. `CCWORK_CLAUDE_DEPTH` guards nested runs. The outer wrapper sets it. A nested
   `claude` call sees it and uses `exec`, so it sends no event.
4. `RepoListModel.apply_hook_event` handles `ClaudeExited` with the same cascade
   as `clear_session(repo_id)`.
5. `MainWindow` calls `session_recovery.clear_open(cwd)` for the event.

### Signals

The wrapper must pass signals through to the child:

| Signal | Expected result |
|---|---|
| Ctrl+C | Claude handles it. The wrapper must not exit first. |
| Ctrl+Z | Claude and the wrapper both stop. `fg` resumes both. |
| SIGHUP (xterm closes) | The child gets it. The wrapper's event can fail silently, because `_on_terminal_finished` covers this case. |

Check each case live before the build is complete.

## Tests

- The `ClaudeExited` cascade clears working, status, subagents and session-active
  for that row only.
- A shell test for `bin/claude`: it returns the child's exit code, a nested call
  sends no event, and the event line is valid JSON.

## Docs

`CLAUDE.md`: the `bin/claude` entry, and the `SessionEnd` note about `/exit`.
