# ccwork guide

Everything ccwork does, in more detail than the [README](../README.md).

## Sidebar rows

<p align="center">
  <img alt="One sidebar row up close, with numbered highlights: 1 row number, 2 row icon, 3 title, 4 repo name, 5 git branch, 6 status text, 7 subagent twinkle, 8 status badge; and the status badge colors" src="images/ccwork-row.png" width="560">
</p>

Each row has three lines:

1. The row icon and a task title. The line is blank when no title is set.
2. `repo | branch`. The branch shows `(detached)` for a detached HEAD and
   `(path missing)` when the directory is gone.
3. What Claude is doing: the badge word, `Working · 2m`, `Compacting`, or
   `Claude open`. A bare shell shows nothing.

Click a repo to bring up its terminal. Right-click for the row menu: reload
the terminal, clone the row, open the folder, copy the path, rebind the row
to another directory, set the title or icon, or remove the row.

The title line of a repo you haven't opened this session is regular italic.
It turns bold upright once a terminal exists.

Turn line 3 off with *Show status text in sidebar rows* in Preferences. The
row keeps its height.

## Status badges

Each row has a status badge, a colored dot at its right edge. The color says
why Claude stopped:

| Color | Meaning | Clears at |
|---|---|---|
| Red | Needs permission | the end of the reply, or your next prompt |
| Orange | Needs an answer | your answer, or your next prompt |
| Magenta | API or account error | your next prompt |
| Yellow | Usage limit | the auto-resume, or your next prompt |
| Green | Done | your next prompt |

Every badge also clears when the Claude session ends.

A violet mark shows while Claude compacts its context. A cyan twinkle beside
the badge shows while subagents run. A dim ⠿ marks a terminal with Claude
open and nothing else to report.

While Claude works on a prompt, the row ticks a small braille spinner. That
is the time from your prompt (`UserPromptSubmit`) to the end of Claude's
reply (`Stop`). A permission prompt does not end the reply: the red badge
takes the spinner's place until the reply ends. Each repo gets one of five
spinner variants (classic rotating, rolling wave, bouncing trio, pulse fill,
center bounce), picked from its id, so the same repo always animates the
same way.

Hover any row for a tooltip that names its state.

## Titles

The row title and the Claude session title are one value, synced in both
directions. Each side picks up a change at your next prompt: `/rename` in
Claude, or right-click → *Set title…* in ccwork.

Claude can name its own row:

```bash
ccwork-rename "fix login bug"           # set the title
ccwork-rename --badge 🐛 "fix login"    # set the title and the row icon
ccwork-rename --badge 🐛                # set only the row icon
```

ccwork tells each new Claude session that the command exists. Outside a
ccwork terminal the command exits with an error.

## Row icons

Right-click a repo → *Set badge…* to put a glyph (an emoji or any single
character) in front of the title. The dialog has a 25-glyph quick-pick
gallery (🐛 🧪 🚀 🔧 🎨 …) and a *Browse system…* button. That button
launches the first system emoji picker it finds: `bemoji`, `rofimoji`,
`gnome-characters`, `gucharmap`, or `kcharselect`. The text field takes any
pasted or typed character. *Clear badge* on the same menu removes the icon.

## Parallel sessions

Add the same repo twice (`Ctrl+Shift+O`, or right-click → *Clone this repo*)
to run parallel Claude sessions on it. Duplicates get Roman-numeral suffixes
(`myrepo (I)`, `myrepo (II)`, …). Remove all but one and the suffix goes
away. Each row shows only its own terminal's Claude state, and icons are set
per row.

When you `cd` into another repo and start `claude`, the row follows the
session and renames itself to that repo.

## Recent and idle repos

A faded half-width *Recent* slot sits under the last row. Click it for a
list of every repo you've removed. Pick one to add it straight back, row
icon and all.

Turn on *Remove idle repos from the sidebar after N days* in Preferences to
let repos clean themselves up. A repo with no Claude activity and no click
for that long moves to the Recent list. Repos with an open terminal stay.

## Dashboard

<img alt="Weekly retro dashboard: a summary sentence, an 8-week commit trend, a release callout, and per-repo cards with radar charts" src="images/ccwork-dashboard.png" width="760">

When no repo is selected, the main pane shows a weekly retro built from
local git. That happens at launch when no repo is restored, after a terminal
closes, and when you click the sidebar's *Dashboard* slot. Every number is a
rolling 7-day window with merges excluded. The page has:

- a plain-language summary of the week
- an 8-week commit trend
- a week-in-numbers row
- a release callout when a tag shipped
- a card per repo with a six-spoke radar chart, churn and file stats
- a strip for repos with no commits this week

The Dashboard slot overlays the view without touching your terminals. Press
Esc, or click the selected repo again, to go back. The page re-reads git
every minute while it is visible. It makes no network calls. With no repos
yet, it shows the logo and keyboard hints instead.

## Crash recovery

If ccwork quits without a clean shutdown, the next launch shows a banner
above the dashboard. It lists the Claude sessions that were open, each with
two buttons: *Copy* puts the session ID on the clipboard, and *Launch* opens
a terminal for that repo running `claude --resume <id>`. *Dismiss* hides the
banner. The list lives in `~/.config/ccwork/`, so it survives a reboot.

## Terminals

Each repo gets a real xterm, embedded in the window through XEmbed (the X11
protocol that puts one app's window inside another). There is no
reimplemented VT100 emulator. ccwork adds a few bindings to each xterm:

- Ctrl+C reaches the shell as usual.
- Ctrl+Shift+C and Ctrl+Shift+V copy and paste with the clipboard.
- A drag-select fills both the clipboard and the middle-click selection.
- The mouse wheel scrolls back.

## Alert bell

The 🔔 in the top bar gets a red dot when any row gets a new badge. Click it
to clear the dot. The 🔊 / 🔇 button beside it turns desktop notifications on
and off.

## Keyboard

| Keys | Action |
|---|---|
| `Ctrl+Shift+P` | Preferences |
| `Ctrl+Shift+O` | Add repo |
| `Ctrl+Shift+Q` | Quit |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Next / previous repo |
| `Ctrl+Shift+1` … `Ctrl+Shift+9` | Jump to row N (the digit shows in each row's top-left corner) |
| `Ctrl+=` / `Ctrl+-` / `Ctrl+0` | Zoom terminals in / out / reset |
| `F1` | Full cheatsheet |

Shortcuts fire only while ccwork has focus. They don't reach your other apps.

## Preferences

Open with the gear button or `Ctrl+Shift+P`. Settings persist to
`~/.config/ccwork/settings.toml`.

**Text tab**

- **Font family / size**: applied live to open terminals.

**Colors tab**

- **Color scheme**: Solarized Dark, Dracula, Gruvbox Dark, Solarized Light,
  GitHub Light, or Tomorrow. Picking one updates the background and
  foreground swatches. Setting either color by hand switches the scheme to
  "Custom".
- **Background / foreground**: color pickers, applied live.

**Scrolling tab**

- **Scrollback**: lines kept in xterm history.
- **Scrollbar**: `right`, `left`, or `none`.
- **Jump scroll**: xterm's fast-redraw mode for bursts of output.

**UI tab**

- **Sidebar position**: left or right.
- **Status badge**: `Colored dot` (default) or `Glyph (! ✓ ·)`. The glyph
  style gives each status its own shape, so it doesn't depend on color.
- **Reopen the last-used repo on launch**: restores focus and the terminal
  at startup. Turn it off to land on the dashboard every launch.
- **Show desktop notifications**: gates the `notify-send` pop-ups from
  `ccwork-hook-sink`. Badges in the window stay on either way. The 🔊 / 🔇
  button in the top bar drives the same setting.
- **Auto-arrange repos by recent Claude activity**: the sidebar reorders
  itself so repos with the most recent Claude activity sit on top. The
  reorder waits about 2 s after the last event, then until you have left
  the sidebar alone for about 800 ms, so rows don't shift under your
  cursor. A row then bubbles up one neighbor at a time, slow at the start
  and end and fast in the middle. The violet "last focused" stripe is your
  navigation, not Claude activity, and never feeds the sort.
- **Group active sessions at the top of the sidebar**: repos running a live
  Claude session float to the top, above a small gap. On by default.
- **Warn before sending Ctrl+Z to the terminal**: Ctrl+Z in a shell
  suspends Claude. With this on, ccwork asks first. On by default.
- **Show status text in sidebar rows**: line 3 of each row. On by default.
- **Remove idle repos from the sidebar after N days**: off by default. The
  day count is greyed out while it is off.

Sidebar width isn't in the dialog. Drag the splitter, and the new width
persists. The narrowest width is about 6 characters; the badge hides before
the text gets narrower than about 4 characters.

**Advanced tab**

- **Extra xterm args**: raw flags added to every xterm launch, parsed with
  shell quoting rules. See `man xterm`.

Unknown keys in `settings.toml` survive a save, so hand-edited fields and
comments stay when ccwork rewrites the file. A legacy `settings.json` is
migrated to `.toml` on first launch.
