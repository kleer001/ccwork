# Setup

## Quick install

```bash
git clone https://github.com/YOUR_USERNAME/ccwork
cd ccwork
./install.sh --dry-run   # preview all changes before touching anything
./install.sh             # apply
source ~/.bashrc
```

The script is idempotent — safe to re-run, skips steps already done. Every file it touches is backed up to `~/.local/share/ccwork/backups/` and all actions are logged to `~/.local/share/ccwork/install.log`.

To undo everything:

```bash
./install.sh --uninstall
source ~/.bashrc
```

---

## Prerequisites

```bash
which zellij       # if missing: https://zellij.dev
which notify-send  # if missing: sudo apt install libnotify-bin
notify-send "test" "if you see a popup, notifications work"
```

If the test popup doesn't appear, your desktop's notification daemon isn't running (uncommon on stock Ubuntu/GNOME, but possible on minimal installs or some tiling WMs).

---

## Manual setup

### 1. Put the `claude` wrapper on your PATH

Clone this repo, then prepend its `bin/` to your PATH in `~/.bashrc`:

```bash
export PATH="/path/to/ccwork/bin:$PATH"
```

The wrapper intercepts `claude` and delegates to your real `claude` binary automatically. Inside a zellij session it also renames the tab to the current directory and passes `--continue` so the last conversation resumes. Outside zellij it is a transparent pass-through.

---

### 2. Configure Zellij session resurrection

When you re-attach to a session, Zellij would normally offer to re-run any commands that were active. To drop straight into a shell instead, add this to `~/.config/zellij/config.kdl`:

```
post_command_discovery_hook "echo $SHELL"
```

---

### 3. Add the `ccwork` alias and shell hooks

Append to `~/.bashrc`:

```bash
alias ccwork='zellij attach --create ccwork'

_zellij_tab_rename() {
    [ -n "$ZELLIJ" ] && zellij action rename-tab "$(basename "$PWD")"
}

_ccwork_hint() {
    [ -z "$ZELLIJ" ] && return
    [ "$PWD" = "$_ccwork_hint_dir" ] && return
    _ccwork_hint_dir="$PWD"
    local _project_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/$(echo "$PWD" | sed 's|/|-|g')"
    ls "$_project_dir"/*.jsonl 2>/dev/null | grep -q . && echo "  Type 'claude' to resume previous session"
}

PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND; }_zellij_tab_rename; _ccwork_hint"
```

Then `source ~/.bashrc`.

---

### 4. Configure Claude Code hooks

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
            "command": "if [ -n \"$ZELLIJ\" ]; then _f=/tmp/ccwork-spinner-${ZELLIJ_PANE_ID}.pid; [ -f $_f ] && { kill $(cat $_f) 2>/dev/null; rm -f $_f; }; zellij action rename-tab \"✓ $(basename \"${CLAUDE_PROJECT_DIR:-$PWD}\")\"; notify-send -u critical \"Claude [$(basename \"${CLAUDE_PROJECT_DIR:-$PWD}\")]\" \"Task done\"; fi"
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
            "command": "if [ -n \"$ZELLIJ\" ]; then _f=/tmp/ccwork-spinner-${ZELLIJ_PANE_ID}.pid; [ -f $_f ] && { kill $(cat $_f) 2>/dev/null; rm -f $_f; }; zellij action rename-tab \"● $(basename \"${CLAUDE_PROJECT_DIR:-$PWD}\")\"; notify-send -u critical \"Claude [$(basename \"${CLAUDE_PROJECT_DIR:-$PWD}\")]\" \"Needs your input\"; fi"
          }
        ]
      }
    ]
  }
}
```

`-u critical` makes notifications persist until dismissed. The project name is pulled from `$CLAUDE_PROJECT_DIR` (set by Claude Code) with `$PWD` as fallback. While Claude is working the tab name shows an animated braille spinner; it switches to `✓` on completion or `●` when input is needed.

---

### Files touched

- `~/.bashrc` — PATH prepend, `ccwork` alias, tab rename hook, resume hint
- `~/.claude/settings.json` — Stop and Notification hooks
- `~/.config/zellij/config.kdl` — session resurrection drops to shell
