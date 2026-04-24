# Setup

## Quick install

```bash
git clone https://github.com/kleer001/ccwork
cd ccwork
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
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
sudo apt install xterm socat python3 git
```

- **xterm** — the terminal that gets reparented into the Qt window.
  `urxvt` also supports `-into` and can be swapped in later.
- **socat** (or fallback: `nc`) — pipes hook JSON into the Unix socket.
- **python3** + **git** — wrapper scripts and prereq checks.

## Wayland

The GUI detects `$WAYLAND_DISPLAY` and forces `QT_QPA_PLATFORM=xcb` so Qt
and xterm both live on X11 (via XWayland). Sessions without XWayland are
not supported — embedding an X-client terminal is X11 only.

## Files touched by install

- `~/.bashrc` — adds `<repo>/bin` to PATH so `ccwork` and the `claude`
  wrapper are found first. Marked with `# BEGIN ccwork` / `# END ccwork`.
- `~/.claude/settings.json` — appends Stop and Notification hooks whose
  `command` is the path of `bin/ccwork-hook-sink`.
- `<repo>/bin/ccwork` — generated launcher that runs `python -m src.main`.
- `~/.local/share/applications/ccwork.desktop` — desktop-menu entry.

## Files ccwork creates at runtime

- `~/.config/ccwork/repos.json` — the sidebar's repo list. Auto-created
  on first add; safe to edit by hand.
- `~/.config/ccwork/settings.json` — Preferences dialog output (xterm
  font / scrollback / scrollbar / colors / extra args). Auto-created on
  first launch with defaults.
- `$XDG_RUNTIME_DIR/ccwork/ccwork.sock` — Unix socket for hook IPC.
  Removed on clean shutdown.

## Tuning the terminal

Open the app → **File → Preferences…** (`Ctrl+,`). Tabs:

- **Text** — font family, font size.
- **Colors** — scheme preset combo (3 dark / 3 light / Custom) plus
  independent bg/fg color pickers.
- **Scrolling** — scrollback lines, scrollbar position, jump scroll.
- **Advanced** — raw xterm flags (shlex-parsed).

On Save, ccwork pushes color + font-face changes to every running
terminal immediately via OSC escape sequences written to the child
PTY (`/dev/pts/N`). For settings xterm only reads at startup (font
size, scrollback, scrollbar), right-click the repo in the sidebar →
**Reload terminal** to respawn xterm.

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

2. **Hooks:** add to `~/.claude/settings.json`:

    ```json
    {
      "hooks": {
        "Stop":         [{"matcher": "*", "hooks": [{"type": "command", "command": "CCWORK_EVENT=Stop /path/to/ccwork/bin/ccwork-hook-sink"}]}],
        "Notification": [{"matcher": "*", "hooks": [{"type": "command", "command": "CCWORK_EVENT=Notification /path/to/ccwork/bin/ccwork-hook-sink"}]}]
      }
    }
    ```

3. **Python deps:** `pip install -r requirements.txt` inside a venv.

4. **Launcher:** `python -m src.main` from the repo root.
