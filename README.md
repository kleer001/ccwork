# ccwork

A Qt desktop GUI for running Claude Code across many repos. One window, a
clickable sidebar of repos, real embedded terminals, and a live alerts panel
driven by Claude Code's Stop/Notification hooks.

## What it does

- **Sidebar of repos** — name + current git branch + unread-alert badge.
  Click a repo to bring up its terminal; right-click for reload / remove.
- **Real embedded terminals** — xterm is reparented into the window via
  XEmbed. Your existing terminal muscle memory (copy/paste, scrollback,
  ctrl-c) all works; no reimplemented VT100 emulator.
- **Auto-resume** — when a repo's terminal spawns, `claude --continue` runs
  automatically if a transcript exists for that project.
- **Alerts panel** — Claude Code's Stop and Notification hooks pipe into a
  top-right list. The matching repo's sidebar gets an unread badge if you
  aren't looking at it.
- **Auto-registration** — running `claude` inside the GUI from a git root
  not yet in the sidebar adds it silently.
- **Preferences dialog** with color-scheme presets (Solarized Dark/Light,
  Dracula, Gruvbox Dark, GitHub Light, Tomorrow), font/scrollback/
  scrollbar controls, and live OSC-based apply for colors.

## Requirements

- Linux, X11 or XWayland (the embedded-xterm model is X11-only).
- `xterm`, `git`, `python3`, plus either `socat` or `nc` for hook IPC.

```bash
sudo apt install xterm socat python3 git
```

## Install

```bash
git clone https://github.com/kleer001/ccwork
cd ccwork
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./install.sh --dry-run   # preview
./install.sh             # apply
source ~/.bashrc         # pick up PATH change
ccwork                   # launch
```

`install.sh` is idempotent — re-run it after upgrading. It backs up every
file it touches to `~/.local/share/ccwork/backups/`.

To undo:

```bash
./install.sh --uninstall
```

## Configuring the terminal

Open **File → Preferences…** (or `Ctrl+,`). Four tabs:

- **Text** — font family (monospace filter) and size.
- **Colors** — preset combo with three dark (Solarized Dark, Dracula,
  Gruvbox Dark) and three light (Solarized Light, GitHub Light, Tomorrow)
  schemes, plus bg/fg color pickers. A live preview pane shows the
  combined font + colors before you save.
- **Scrolling** — scrollback lines (default **20,000**), scrollbar
  position (right/left/none), jump scroll toggle.
- **Advanced** — raw xterm extra args (shlex-parsed), e.g.
  `-bdc -xrm 'XTerm*cursorBlink: true'`.

Saved to `~/.config/ccwork/settings.json`.

**Live apply**: colors (foreground, background, cursor) and font family
are pushed to every running terminal immediately — ccwork writes the
corresponding xterm OSC escape sequences (`OSC 10/11/12/50`) to each
terminal's PTY. No `xtermcontrol` binary needed.

**Needs a reload**: font size, scrollback, scrollbar position, jump
scroll, and raw extra args are read by xterm only at startup. After
saving, ccwork's status bar tells you if a reload is needed. Right-click
the repo in the sidebar → **Reload terminal** to respawn xterm with the
current settings.

### Mouse / keyboard in xterm

- Mouse wheel scrolls the scrollback (ccwork sets this up automatically).
- `Shift+PgUp` / `Shift+PgDn` — page through scrollback.
- `Ctrl+left-click` inside the terminal → main xterm options menu.
- `Ctrl+middle-click` → VT fonts menu (resize text live).

ccwork cannot directly import konsole profiles — the formats differ — but
every knob konsole exposes (font, colors, scrollback, bell) maps to an
xterm flag you can put in the Extra args field.

## How it fits together

```
Claude Code  ──Stop / Notification──▶  bin/ccwork-hook-sink  ──▶  Unix socket  ──▶  Qt GUI
                                                                                   │
bin/claude wrapper  ──CCWORK_GUI=1 + RepoAdded──────────────────────────────────────┘
```

- `bin/claude` is a thin bash wrapper that finds the real `claude` on PATH,
  resumes the last conversation when possible, and pings the GUI over the
  socket when invoked from inside it.
- `bin/ccwork-hook-sink` is a bash one-liner that Claude Code's hooks
  invoke. It wraps the hook payload in JSON and writes it to the socket.
- The GUI listens on `$XDG_RUNTIME_DIR/ccwork/ccwork.sock`.

## Under Wayland

The GUI forces `QT_QPA_PLATFORM=xcb` if `$WAYLAND_DISPLAY` is set so both Qt
and xterm run through XWayland. Pure Wayland sessions without XWayland are
not supported.

## Non-goals (for now)

- Multi-tab terminals per repo
- Cross-OS support — MVP is Linux-only
- In-app Claude Code conversation browser
- Theming beyond Qt's default

## License

MIT — see `LICENSE`.
