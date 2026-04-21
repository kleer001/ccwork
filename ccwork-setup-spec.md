# ccwork: Claude Code in zellij with desktop notifications

Personal setup spec for running Claude Code on Ubuntu with tabs, persistent sessions, and alerts when Claude finishes or needs input.

## Design

- **zellij** — terminal multiplexer. Provides tabs + session persistence.
- **notify-send** — Ubuntu's built-in desktop notifications.
- **Claude Code hooks** — native feature. Fires shell commands on `Stop` and `Notification` events.

No wrapper scripts. No custom TUI. No layout file. Zellij starts empty; you add tabs when you want them, `cd` into whatever repo, and run `claude`.

---

## Pre-flight checks

```bash
which notify-send   # if missing: sudo apt install libnotify-bin
which claude        # should already exist
echo $SHELL         # zellij will use this shell, so your .bashrc applies inside tabs
notify-send "test" "if you see a popup, notifications work"
```

If the test popup doesn't appear, your desktop's notification daemon isn't running (uncommon on stock Ubuntu/GNOME, but possible on minimal installs or some tiling WMs).

---

## Step 1: Install zellij

Prebuilt binary (no Rust toolchain needed):

```bash
cd /tmp
curl -L https://github.com/zellij-org/zellij/releases/latest/download/zellij-x86_64-unknown-linux-musl.tar.gz | tar xz
sudo mv zellij /usr/local/bin/
zellij --version
```

Alternative if you already have Rust: `cargo install --locked zellij`.

---

## Step 2: Add the `ccwork` alias

Append to `~/.bashrc`:

```bash
alias ccwork='zellij attach --create ccwork'
```

Then `source ~/.bashrc`.

**What `--create ccwork` does:** attaches to a session named `ccwork` if one exists, creates it if it doesn't. This is the persistence: close the terminal, come back hours later, run `ccwork`, every tab and its working directory is still there.

---

## Step 3: Configure Claude Code notification hooks

Edit `~/.claude/settings.json` (create if it doesn't exist). If the file already has content, merge the `hooks` block in — don't overwrite.

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "notify-send \"Claude [$(basename \"${CLAUDE_PROJECT_DIR:-$PWD}\")]\" \"Task done\""
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
            "command": "notify-send \"Claude [$(basename \"${CLAUDE_PROJECT_DIR:-$PWD}\")]\" \"Needs your input\""
          }
        ]
      }
    ]
  }
}
```

**What shows up:** popups titled e.g. *"Claude [my-repo]"* with body *"Task done"* or *"Needs your input"*. The repo name is derived from `$CLAUDE_PROJECT_DIR` (set by Claude Code) with `$PWD` as fallback.

---

## Daily usage

1. Open any terminal. Type `ccwork`.
2. First run: empty zellij session, one blank tab.
3. To open a new tab: `Ctrl+t` then `n`. Rename with `Ctrl+t` then `r`.
4. `cd` to whatever repo you want in that tab.
5. Run `claude` when you're ready to start.
6. Switch tabs: `Ctrl+t` then arrow keys, or `Ctrl+t` then a number.
7. Done for the day? Close the terminal window. Session keeps running in the background.
8. Next time: `ccwork` reattaches. All tabs, all `cd` locations intact.

Notifications fire from any tab — you don't have to be looking at zellij when Claude finishes or needs you.

---

## zellij keybindings you'll actually use

Zellij is modal. You press a Ctrl-key to enter a mode, then a letter for the action. The status bar at the bottom shows available keys in the current mode, so nothing to memorize.

| Action | Keys |
|---|---|
| New tab | `Ctrl+t` then `n` |
| Switch tabs | `Ctrl+t` then `←` / `→` (or a number) |
| Rename tab | `Ctrl+t` then `r` |
| Close tab | `Ctrl+t` then `x` |
| Detach (keep session running) | `Ctrl+o` then `d` |
| Quit session entirely | `Ctrl+q` |
| Lock mode (pass through all keys to app) | `Ctrl+g` — toggle |

**Lock mode matters** if you use Neovim or anything else that wants `Ctrl+t`/`Ctrl+p`/`Ctrl+o`. Toggle lock with `Ctrl+g` to pass everything through to the app.

---

## Useful session commands (from outside zellij)

```bash
zellij list-sessions                # see what's running
zellij kill-session ccwork          # nuke the ccwork session
zellij attach --create other-name   # spin up a second parallel session for a different context
```

---

## Later extensions (not for MVP)

- **Sound alert:** append ` && paplay /usr/share/sounds/freedesktop/stereo/complete.oga` to the hook command.
- **Richer message:** parse the JSON Claude pipes to the hook on stdin (contains transcript path, event type, etc.) to include the last sentence of Claude's reply. See https://docs.claude.com/en/docs/claude-code/hooks
- **Per-project hooks:** put a `.claude/settings.json` inside a repo to override the global hooks for that project only.

---

## Files touched

- `~/.bashrc` — one alias line
- `~/.claude/settings.json` — hooks block
- `/usr/local/bin/zellij` — the binary

That's it. Easy to tear down, easy to reproduce on a new machine.
