# ccwork: Retool from tmux wrapper to PyQt GUI

## Context

ccwork today is a bash-layer tmux/zellij wrapper for `claude`: it renames panes, animates a braille spinner, auto-resumes the last conversation, and relays Stop/Notification hooks via `notify-send`. The terminal-multiplexer substrate has hit its ceiling — no clickable repo list, no real mouse in panes, no stable "current repo" header, and alerts are transient OS toasts.

**Goal:** replace the tmux/zellij substrate with a native Qt desktop app that owns the window chrome itself. MVP borrows tuicommander's layout:

- **Left:** sidebar of repo buttons (click to focus that repo's terminal). Each button shows repo name + current git branch as subtitle + unread-alert badge.
- **Center:** one embedded real terminal per repo.
- **Top strip:** `[current repo name .................. alerts panel]` — repo name left-aligned, recent alerts list right-aligned.

Constraints from the user:
- Native OS look; **no web-tech** (so no Electron/Tauri/xterm.js).
- Trust Python + Qt over turbulent JS frameworks.
- Keep everything in the ccwork repo — this is a retool, not a new project.
- **Hijack a real system terminal** (xterm) into the Qt window rather than emulate VT100 ourselves.
- tmux stays only if strictly needed, and if used, must be thin and dumb: session persistence only, no hooks/renames/spinners.
- Repos: user-navigated + autopopulate when `claude` is launched in a new git root + manual "+ Add Repo" button.
- Alerts driven by the existing Claude Code Stop/Notification hooks (shape stays the same; the sink changes).
- Keep the beloved `--continue` auto-resume behavior from current `bin/claude`.

## Stack choice

- **PySide6** (LGPL, official Qt-for-Python) — preferred over PyQt6 (GPL) so redistribution is unconstrained.
- **Embedded xterm via XEmbed.** Launch `xterm -into <winId>` as a child `QProcess` reparented into a `QWidget` placeholder. xterm renders the shell; Qt owns the chrome. Zero VT100 emulation code to write or maintain.
  - Works on X11 natively. Works on Wayland sessions by forcing Qt under XWayland (`QT_QPA_PLATFORM=xcb`) so both Qt and xterm are X11 clients and reparenting succeeds.
  - Resize: xterm does **not** auto-resize to container; handle `QWidget.resizeEvent` → compute new char cells → send `SIGWINCH` to xterm PID (xterm picks up the terminal size from its X window via XResize and its TIOCSWINSZ from the signal).
  - Not every modern terminal supports `-into`: xterm and urxvt do; alacritty/kitty/gnome-terminal don't. Ship xterm as default; urxvt as a config option later.
- **tmux (optional, off by default)** — used only as "session persistence" by wrapping the xterm command as `xterm -into <winId> -e tmux new -A -s ccwork-<repo_slug>`. No tmux hooks, no renames. Toggle per-repo in config; off by default for MVP.
- **Claude Code resume** — when spawning a repo's terminal, if `~/.claude/projects/<slug>/*.jsonl` exists, invoke `claude --continue` as the xterm `-e` command (or in the user's shell via `CCWORK_AUTO_RESUME=1`). Port the slug-building logic from current `bin/claude` into Python.
- **QLocalServer/QLocalSocket** (Unix domain socket under `$XDG_RUNTIME_DIR`, `~/Library/Application Support/ccwork/` on Darwin) for hook → GUI IPC.
- **bash** for the hook sink script — ~150ms Python startup is too much for a per-event hook. Bash + `socat` (or `nc -UN`) pipes stdin straight to the socket.
- **stdlib `json`** for repo persistence. No DB.

**Rejected / deferred:**
- **pyte + custom QWidget terminal** — rendering a full VT100/xterm emulator to the quality Claude Code's TUI needs is weeks of work. Defer as a cross-OS fallback if ccwork ever targets macOS/Windows.
- **QTermWidget / termqt** — viable cross-OS fallback path (termqt-pyside6 is published), but MVP stays on embedded xterm for zero emulator maintenance.
- **Electron/Tauri** — explicitly ruled out.

## Architecture

```
ccwork/
├── bin/
│   ├── claude                  # rewrite: thin Python or bash shim.
│   │                           #   - if $CCWORK_GUI=1 and $PWD is a git root not in repos.json,
│   │                           #     pings the local socket with event=RepoAdded, cwd=$PWD
│   │                           #   - computes Claude Code project slug; if history exists, exec `claude --continue "$@"`
│   │                           #   - else exec `claude "$@"`
│   └── ccwork-hook-sink        # NEW: bash one-liner. Reads stdin, wraps in {event,cwd,ts}, writes to socket via socat.
├── src/
│   ├── main.py                 # entry: QApplication + MainWindow; sets QT_QPA_PLATFORM=xcb if Wayland detected
│   ├── ui/
│   │   ├── main_window.py      # QMainWindow. Layout: vertical — top strip (title + alerts) / horizontal (sidebar | terminal stack)
│   │   ├── repo_sidebar.py     # QListView + custom delegate: name, branch subtitle, unread badge pill. "+ Add Repo" button at bottom.
│   │   ├── terminal_host.py    # QWidget placeholder; owns QProcess running xterm -into self.winId(); handles resizeEvent→SIGWINCH
│   │   ├── alerts_panel.py     # top-right QListView of recent Stop/Notification events, truncated to N most recent
│   │   └── title_label.py      # large QLabel showing current repo name; bound to sidebar selection signal
│   ├── core/
│   │   ├── repo_store.py       # load/save ~/.config/ccwork/repos.json; add/remove/reorder; git-branch lookup
│   │   ├── terminal_session.py # per-repo: owns TerminalHost, builds xterm argv (with/without tmux wrap, with/without --continue)
│   │   ├── hook_server.py      # QLocalServer on ccwork.sock; parses JSON lines; emits PySide6 signals per event type
│   │   └── claude_slug.py      # mirrors current bin/claude slug logic (/_./ → -) and last-transcript detection
│   └── __init__.py
├── install.sh                  # update: swap hook command → ccwork-hook-sink; drop tmux automatic-rename line and PROMPT_COMMAND;
│                               #         add `ccwork` to PATH; install .desktop file.
├── requirements.txt            # + PySide6  (no pyte, no ptyprocess — xterm owns the PTY)
└── tests/
    ├── test_repo_store.py      # persistence + branch lookup round-trip
    └── test_claude_slug.py     # slug + last-transcript resolution parity with current bin/claude
```

### Data flow

1. **Launch:** `ccwork` starts the Qt app. Detects Wayland (`$WAYLAND_DISPLAY`) and sets `QT_QPA_PLATFORM=xcb` before `QApplication` instantiation to guarantee XEmbed works. Creates config dir + hook socket on first run.
2. **Repo sidebar:** reads `repos.json`. Delegate renders: `name` (bold), `branch` (subtitle, `git symbolic-ref --short HEAD` cached per repo + refreshed on focus), `unread_count` badge if >0. Clicking an item switches the central `QStackedWidget` to that repo's `TerminalHost` (lazy-spawn the first time).
3. **Terminal:** `TerminalHost` is a `QWidget` whose `winId()` is passed to `xterm -into`. `terminal_session.py` builds argv:
   ```
   xterm -into <winId> -fa Monospace -fs 11 -bg black -fg white \
       [-e tmux new -A -s ccwork-<slug>]       # only if persistence enabled
       [-e claude --continue]                   # if history exists and auto-resume on
       [-e $SHELL]                              # fallback
   ```
   QProcess tracks the xterm PID. `resizeEvent` → compute char cells from font metrics → `os.kill(pid, SIGWINCH)`.
4. **Title strip:** title label bound to sidebar `currentChanged` signal; alerts panel sits to its right.
5. **Alerts:** `HookServer` listens on `ccwork.sock`. `ccwork-hook-sink` (bash) reads the hook JSON from stdin, wraps it as `{"event":"Stop"|"Notification","payload":<orig>,"ts":<epoch>}`, writes one newline-terminated line to the socket. GUI appends to `AlertsPanel`, and if `payload.cwd` matches a known repo, increments that repo's unread badge.
6. **Autopopulate on `claude`:** GUI-spawned shells export `CCWORK_GUI=1` in the xterm env. `bin/claude` checks: if `CCWORK_GUI=1` and `$PWD` is a git root not in `repos.json`, sends `{"event":"RepoAdded","cwd":"$PWD"}` to the socket, then exec's the real `claude`. Running `claude` outside the GUI (no `CCWORK_GUI`) is a plain passthrough — no registration. This is the explicit tradeoff: autopopulate only works from inside the app.
7. **"+ Add Repo":** `QFileDialog.getExistingDirectory()` → `repo_store.add()` → sidebar refresh.
8. **Resume last conversation:** port current `bin/claude` logic into `core/claude_slug.py`. When a repo terminal spawns, check for `~/.claude/projects/<slug>/*.jsonl`; if present, exec `claude --continue`, else `claude` plain.

### Hook integration

Current `install.sh` writes Stop/Notification hooks whose `command` is an inline bash snippet doing `notify-send` + tmux rename. The rewrite replaces that `command` string with `/home/menser/Dropbox/ai/code/ccwork/bin/ccwork-hook-sink`. No stdin change — Claude Code already pipes the hook payload; the sink just forwards it. The install.sh idempotent merge logic that preserves other hooks stays as-is.

## Files to modify / create

**Create:**
- `src/main.py`, `src/ui/{main_window,repo_sidebar,terminal_host,alerts_panel,title_label}.py`, `src/core/{repo_store,terminal_session,hook_server,claude_slug}.py`
- `bin/ccwork-hook-sink` (bash)
- `tests/test_repo_store.py`, `tests/test_claude_slug.py`

**Rewrite:**
- `bin/claude` — strip tmux/zellij/spinner logic. Keep slug computation + `--continue` resume (now shared with GUI via `core/claude_slug.py`). Add `CCWORK_GUI`-gated repo-registration ping.
- `install.sh` — swap Stop/Notification hook `command` payloads to `ccwork-hook-sink`; drop tmux `automatic-rename off` and `PROMPT_COMMAND` additions; add `ccwork` launcher to PATH; install `.desktop` file; ensure xterm is a documented dependency.
- `requirements.txt` — add PySide6. Remove any pyte/ptyprocess references (not using them).
- `README.md`, `docs/setup.md` — rewrite for GUI flow; document xterm dependency and XWayland note.

**Delete:**
- `/tmp/ccwork-spinner-*.pid` handling, braille spinner animation, zellij-specific branches in `bin/claude`.

## Reuse / don't reinvent

- `install.sh`'s idempotent hook-merge logic — keep as-is.
- Claude Code project slug convention (from current `bin/claude`) — move into `core/claude_slug.py` and share between GUI and wrapper.
- Existing `--continue` resume flow — preserved verbatim, just relocated.

## Not-MVP (out of scope)

- Multi-tab terminals per repo
- In-app conversation history browser
- tuicommander-style `SidebarPanelHandle` plugin system
- Command palette / search
- Theming beyond Qt default + a dark stylesheet
- Cross-OS support (macOS/Windows) — the embedded-xterm choice means MVP is Linux-only. If cross-OS becomes a goal, swap `TerminalHost` for a termqt/QTermWidget-backed widget; the rest of the app doesn't change.

## Verification

1. `pip install -r requirements.txt` in a venv; `python -m src.main` launches a window; xterm is present on `$PATH`.
2. Sidebar starts empty; "+ Add Repo" → pick `~/Dropbox/ai/code/ccwork` → button appears with name + current branch subtitle.
3. Click the repo → xterm embeds in the center, shell prompt in that cwd. Typing works. Resize the window → terminal cols/rows update (no visible wrap breakage).
4. Mouse click inside the terminal focuses the cursor; copy/paste via xterm's native selection works.
5. Run `claude` in the embedded terminal. Confirm that if the cwd is a new git root, a second entry appears in the sidebar automatically (CCWORK_GUI path).
6. End a short Claude session → Stop alert appears in the top-right panel. Trigger a Notification → alert appears and the matching repo's sidebar badge increments.
7. Relaunch the app with tmux persistence enabled for one repo; prior session still visible on reattach.
8. `./install.sh --dry-run` shows updated hook payloads; `./install.sh` then `--uninstall` round-trips cleanly.
9. `pytest tests/` passes.
10. On a Wayland session, confirm the app launches under XWayland and xterm embeds correctly (`echo $XDG_SESSION_TYPE` = wayland, `xlsclients` shows xterm).

## Open risks

- **Wayland-native sessions.** If the user's Qt ever runs as a pure Wayland client (no XWayland), XEmbed fails. Mitigation: force `QT_QPA_PLATFORM=xcb` at startup. If a user explicitly wants native Wayland, they lose embedded-xterm — swap in termqt.
- **xterm resize fidelity.** SIGWINCH + font-metric-driven cell math needs tuning; initial versions may show one-cell-off layouts on resize. Acceptable and iterable.
- **Focus/keyboard edge cases.** Xembedded xterm captures keyboard when focused; Qt shortcuts (e.g. Ctrl+Tab to switch repos) must be registered as application-level shortcuts that xterm can't intercept, or routed via a modifier xterm passes through. Expect one or two iterations.
- **xterm availability.** Ship a clear install hint if `xterm` is missing; don't fall back silently.
