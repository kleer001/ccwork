# Setup

## Quick install

```bash
git clone https://github.com/kleer001/ccwork
cd ccwork
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
./install.sh --dry-run   # preview every change before it happens
./install.sh             # apply
source ~/.bashrc
ccwork                   # launch
```

`install.sh` is idempotent — safe to re-run. Every file it touches is backed
up to `~/.local/share/ccwork/backups/` and actions are logged to
`~/.local/share/ccwork/install.log`.

## Prerequisites

```bash
sudo apt install git python3 python3-venv xterm socat libxcb-cursor0
```

- **xterm** — the terminal that gets reparented into the Qt window.
  `urxvt` also supports `-into` and can be swapped in later.
- **socat** (or fallback: `nc`) — pipes hook JSON into the Unix socket.
- **python3** + **git** — wrapper scripts and prereq checks.
- **libxcb-cursor0** — Qt needs it to open a window on X11. Ubuntu's
  desktop install does not include it.

## Wayland

The GUI detects `$WAYLAND_DISPLAY` and forces `QT_QPA_PLATFORM=xcb` so Qt
and xterm both live on X11 (via XWayland). Sessions without XWayland are
not supported — embedding an X-client terminal is X11 only.

## Files touched by install

- `~/.bashrc` — adds `<repo>/bin` to PATH so `ccwork` and the `claude`
  wrapper are found first. Marked with `# BEGIN ccwork` / `# END ccwork`.
- `~/.claude/settings.json` — adds one hook entry for each Claude Code
  event that ccwork uses (`new_hooks` in `install.sh`). Each `command` runs
  `bin/ccwork-hook-sink`.
- `~/.local/share/applications/ccwork.desktop` — desktop-menu entry.

## Files ccwork creates at runtime

- `~/.config/ccwork/repos.json` — the sidebar's repo list. Auto-created
  on first add; safe to edit by hand.
- `~/.config/ccwork/settings.toml` — the Preferences settings.
  Auto-created on first launch with defaults.
- `~/.config/ccwork/open_sessions.json` — the open Claude sessions, for
  crash recovery.
- `$XDG_RUNTIME_DIR/ccwork/ccwork.sock` — Unix socket for hook IPC.
  Removed on clean shutdown.

## Tuning the terminal

The [guide](guide.md#preferences) lists each Preferences setting.

## Uninstall

```bash
./install.sh --uninstall
source ~/.bashrc
```

The uninstaller strips the `# BEGIN ccwork` block from bashrc, removes the
ccwork entries from `~/.claude/settings.json` (leaving other hooks intact),
and deletes the desktop file.

## Manual setup

The installer is a thin wrapper. If you prefer to wire it up yourself:

1. **PATH:** prepend `<repo>/bin` to your shell rc so `ccwork` and the
   `claude` wrapper take precedence.

2. **Hooks:** add to `~/.claude/settings.json` the entries of `new_hooks`
   in `install.sh`, one for each event. Each one has this shape:

    ```json
    {
      "hooks": {
        "Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "CCWORK_EVENT=Stop /path/to/ccwork/bin/ccwork-hook-sink"}]}]
      }
    }
    ```

3. **Python deps:** `pip install -e '.[dev]'` inside a venv.

4. **Launcher:** `python -m src.main` from the repo root.
