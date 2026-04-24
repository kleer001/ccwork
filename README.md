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
- **Alerts panel** — Claude Code's Stop and Notification hooks pipe into a
  top-right list. Click an entry to jump to that repo; the matching
  sidebar row gets an unread badge if you weren't looking at it.
- **Auto-registration** — running `claude` inside the GUI from a git root
  not yet in the sidebar adds it silently.
- **Preferences dialog** with color-scheme presets (Solarized Dark/Light,
  Dracula, Gruvbox Dark, GitHub Light, Tomorrow), font/scrollback/
  scrollbar controls, and live OSC-based apply for colors and fonts.

## Install

Linux with X11 or XWayland. Requires `git`, `python3`, `python3-venv`,
`xterm`, and either `socat` or `nc`.

```bash
sudo apt install git python3 python3-venv xterm socat
```

One-line bootstrap:

```bash
bash -c "$(curl -sSfL https://raw.githubusercontent.com/kleer001/ccwork/main/bootstrap.sh)"
```

Clones into `~/ccwork` (override with `CCWORK_DEST=…`), creates a venv,
installs dependencies, wires up PATH + hooks + a `.desktop` launcher, and
is safe to re-run for upgrades.

<details>
<summary><b>Manual install</b></summary>

```bash
git clone https://github.com/kleer001/ccwork ~/ccwork
cd ~/ccwork
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./install.sh --dry-run   # preview
./install.sh             # apply
source ~/.bashrc         # pick up PATH change
ccwork                   # launch
```

`install.sh` is idempotent — re-run it after upgrading. It writes only
under `$HOME` (no sudo), backs up every file it touches to
`~/.local/share/ccwork/backups/`, and supports `--uninstall` to revert.

</details>
