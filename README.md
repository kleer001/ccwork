# ccwork

A Qt desktop GUI for running Claude Code across many repos. One window, a
clickable sidebar of repos, real embedded terminals, and a live alerts panel
driven by Claude Code's Stop/Notification hooks.

## What it does

- **Sidebar of repos** — name + current git branch + unread-alert badge.
  Click a repo to bring up its terminal; right-click for reload / remove.
- **Multiple sessions per repo** — `Ctrl+O` the same repo twice to spawn
  parallel Claude sessions on it. Duplicates get Roman-numeral suffixes
  (`myrepo (I)`, `myrepo (II)`, …); remove all but one and the suffix
  disappears. Hook events (status badge, working spinner) currently light
  up every duplicate row for that path — per-session routing is future
  work.
- **Real embedded terminals** — xterm is reparented into the window via
  XEmbed. Your existing terminal muscle memory (copy/paste, scrollback,
  ctrl-c) all works; no reimplemented VT100 emulator.
- **Alerts panel** — Claude Code's Stop and Notification hooks pipe into a
  top-right list. Click an entry to jump to that repo; the matching
  sidebar row gets an unread badge if you weren't looking at it.
- **Auto-registration** — running `claude` inside the GUI from a git root
  not yet in the sidebar adds it silently. Auto-add only fires when no row
  exists for that path; duplicates require manual `Ctrl+O`.
- **Preferences dialog** with color-scheme presets (Solarized Dark/Light,
  Dracula, Gruvbox Dark, GitHub Light, Tomorrow), font/scrollback/
  scrollbar controls, and live OSC-based apply for colors and fonts.

<details>
<summary><b>Preferences reference</b></summary>

Open with the gear button or `Ctrl+,`. Settings persist to
`~/.config/ccwork/settings.json`.

**Text tab**

- **Font family / size** — applied live to running terminals via OSC.

**Colors tab**

- **Color scheme** — preset palette dropdown (Solarized Dark/Light, Dracula,
  Gruvbox Dark, GitHub Light, Tomorrow). Picking one updates the bg/fg
  swatches; setting bg/fg by hand falls the scheme back to "Custom".
- **Background / foreground** — direct color pickers, applied live.

**Scrolling tab**

- **Scrollback** — lines retained in xterm history.
- **Scrollbar** — `right`, `left`, or `off`.
- **Jump scroll** — xterm's fast-redraw mode for bursts of output.

**UI tab**

- **Sidebar position** — left or right.
- **Status badge** — `Colored dot` (default) or `Glyph (! ✓ ·)`. The glyph
  variant is more legible at narrow sidebar widths and colorblind-friendlier.
  Hover any row for a tooltip describing the current state.
- **Reopen the last-used repo on launch** — restores focus + terminal on
  startup.
- **Show desktop notifications** — gates `notify-send` pop-ups from
  `ccwork-hook-sink`. In-window indicators (badges, sidebar colors) stay
  on regardless. Mirrored by the 🔊 / 🔇 toggle in the top bar — both
  surfaces drive the same setting.
- **Auto-arrange repos by recent Claude activity** — when on, the sidebar
  reorders itself so repos with the most recent Stop / Notification /
  UserPromptSubmit events sit on top. Reorder is debounced ~2 s after the
  last event so rows don't shift while you're reading them. The violet
  "last focused" dot is user navigation, not Claude activity, and never
  feeds the sort.

Sidebar width isn't in the dialog — drag the splitter; the new width
persists. Drag floor is ~6 characters wide; the badge auto-hides before
text is squeezed below ~4 chars.

**Advanced tab**

- **Extra xterm args** — raw flags appended to every xterm spawn, parsed
  with shell quoting rules. See `man xterm`.

Unknown keys in `settings.json` round-trip on save, so hand-edited fields
not exposed by the dialog aren't dropped when ccwork rewrites the file.

</details>

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

```bash
# Preview without touching anything:
bash -c "$(curl -sSfL https://raw.githubusercontent.com/kleer001/ccwork/main/bootstrap.sh)" -- --dry-run

# Full flag list:
bash -c "$(curl -sSfL https://raw.githubusercontent.com/kleer001/ccwork/main/bootstrap.sh)" -- --help

# Clean uninstall:
bash -c "$(curl -sSfL https://raw.githubusercontent.com/kleer001/ccwork/main/bootstrap.sh)" -- --uninstall
```

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
