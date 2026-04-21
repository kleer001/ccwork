# ccwork

Claude Code in zellij with persistent sessions and desktop notifications.

## What it does

- **Persistent tabs** — one `ccwork` command attaches to (or creates) a named zellij session. Close the terminal, come back later, everything is still there.
- **Desktop notifications** — when Claude finishes a task or needs your input, a popup appears. Only fires inside zellij tabs; silent when running `claude` outside a session.
- **Auto-named tabs** — each tab automatically renames itself to the current directory.

## Setup

### Prerequisites

```bash
which zellij       # if missing: https://zellij.dev
which notify-send  # if missing: sudo apt install libnotify-bin
which claude       # Claude Code CLI
notify-send "test" "if you see a popup, notifications work"
```

### 1. Add the alias

Append to `~/.bashrc`:

```bash
alias ccwork='zellij attach --create ccwork'
```

### 2. Add tab auto-rename

Append to `~/.bashrc`:

```bash
_zellij_tab_rename() {
    [ -n "$ZELLIJ" ] && zellij action rename-tab "$(basename "$PWD")"
}
PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND; }_zellij_tab_rename"
```

Then `source ~/.bashrc`.

### 3. Configure Claude Code hooks

Merge into `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "[ -n \"$ZELLIJ\" ] && notify-send -u critical \"Claude [$(basename \"${CLAUDE_PROJECT_DIR:-$PWD}\")]\" \"Task done\""
          }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "[ -n \"$ZELLIJ\" ] && notify-send -u critical \"Claude [$(basename \"${CLAUDE_PROJECT_DIR:-$PWD}\")]\" \"Needs your input\""
          }
        ]
      }
    ]
  }
}
```

`-u critical` makes notifications persist until dismissed. The project name is pulled from `$CLAUDE_PROJECT_DIR` (set by Claude Code) with `$PWD` as fallback.

## Daily use

1. `ccwork` — attach or create the session
2. `Ctrl+t` then `n` — new tab
3. `cd` into a repo — tab renames automatically
4. `claude` — start Claude Code
5. Close the window when done — session keeps running
6. `ccwork` again later — all tabs intact

## Key bindings

| Action | Keys |
|---|---|
| New tab | `Ctrl+t` → `n` |
| Switch tabs | `Ctrl+t` → `←` / `→` |
| Rename tab | `Ctrl+t` → `r` |
| Close tab | `Ctrl+t` → `x` |
| Detach (keep session) | `Ctrl+o` → `d` |
| Lock mode (pass keys to app) | `Ctrl+g` — toggle |

## Files touched

- `~/.bashrc` — alias + tab rename hook
- `~/.claude/settings.json` — Stop and Notification hooks
