# Cross-platform roadmap

ccwork v0.1.0 ships **Linux + X11/XWayland only**. This document scopes the
realistic paths to Wayland-native, macOS, and Windows. It is a planning
artifact; nothing here has been implemented.

The audience is a future contributor (or future-us) who needs to decide
where to spend porting effort. It names tradeoffs, not hours.

---

## Constraints today (load-bearing assumptions)

These are the assumptions the current code is built on. Every cross-platform
target invalidates at least three of them:

1. **XEmbed.** `src/ui/terminal_host.py` spawns `xterm -into self.winId()` and
   relies on xterm reparenting itself into our `QWidget` window. There is no
   Wayland-native equivalent; macOS and Windows have nothing analogous.
2. **libX11 ctypes wrapper** at `src/core/x11.py` (~230 lines) for window
   geometry, focus, and resize. Pure X11. Will not load without `libX11.so`.
3. **OSC writes to `/dev/pts/N`** in `src/core/xterm_osc.py` to apply theme
   and font live without respawning. The PTY-slave path is POSIX; the
   "find xterm's PTY by walking /proc" trick is Linux-specific.
4. **`QT_QPA_PLATFORM=xcb` forcing** in `src/main.py` before any Qt import.
   On Wayland this routes Qt through XWayland so XEmbed works. On macOS or
   Windows this env var is a no-op (the platform plugins are `cocoa` /
   `windows`), and the underlying technique doesn't translate.
5. **Bash-script `bin/` layer** — `bin/claude` (PATH shadow), `bin/ccwork-hook-sink`,
   `bin/ccwork-bashrc`, `install.sh`, `bootstrap.sh`. All assume bash, POSIX
   utilities, `~/.config`, `~/.local/share`, and `XDG_RUNTIME_DIR`.

What *does* survive a port: the Qt UI layer (`MainWindow`, `RepoSidebar`,
preferences dialog), the settings round-trip with `_raw`, the hook server
(once the socket abstraction is widened), the repo store, and the event
flow. That's a meaningful fraction of the code, but the terminal subsystem
is the load-bearing half — and it has to be replaced, not patched.

---

## Wayland-native Linux

### What blocks ccwork today

- XEmbed has no Wayland equivalent. There is no protocol for one client to
  embed another's surface; the closest, `xdg-foreign`, exports surfaces for
  cross-process referencing (e.g. parent-window hints) but does **not**
  reparent rendering. See the `wprs` issue tracker discussion of why this
  is unlikely to land.
- `src/core/x11.py` won't function under Wayland. Even if Qt runs natively,
  there is no X server to call.
- The OSC-to-PTS trick still works on a Wayland-native build (PTYs are
  unrelated to display server) **provided** we still control a PTY. With
  an embedded terminal widget that owns its emulator, we can apply OSC
  directly to the master fd instead of poking `/dev/pts/N` through the
  filesystem — cleaner, not harder.

### Candidate approaches

1. **`termqt` (Python + Qt terminal widget).**
   <https://github.com/TerryGeng/termqt> plus the PySide6 fork at
   <https://github.com/Sun-ZhenXing/termqt-pyside6>. Single maintainer,
   small code base. Pros: pure Python, drop-in QWidget, MIT-ish.
   Cons: TUI fidelity for Claude Code's full-screen alt-screen UI is
   **unverified** — needs a soak test. 256-color + truecolor support
   present; mouse and bracketed paste claimed; sixel no.
   Cost: **small to medium** (1–2 weeks for the widget swap behind a flag,
   plus an unknown bucket if Claude's TUI exposes bugs).

2. **QTermWidget (Konsole-derived, used by lxqt).**
   <https://github.com/lxqt/qtermwidget>. Mature, Qt6-compatible. Cons:
   **GPL** (license re-evaluation needed; ccwork is currently
   permissive-license-friendly), C++ — **no PySide6 bindings exist**, so
   either generate them with `shiboken6` (large, never trivial) or invoke
   via a thin C++ stub. Either way, build complexity jumps from "pip
   install" to "compile-time toolchain."
   Cost: **large**.

3. **`pyte` + custom QWidget renderer.**
   <https://github.com/selectel/pyte>. pyte parses the byte stream into a
   screen model; the renderer is on us. Effectively writing a terminal
   emulator widget. We get full control of font metrics, OSC routing,
   theming, but we own every bug. Estimating "weeks" is optimistic;
   "months to reach feature parity with xterm for a TUI as demanding as
   Claude Code" is more honest.
   Cost: **large**.

4. **VTE (GTK).** The widget GNOME Terminal uses. It's GTK-only — there is
   no Qt embedding path. Adopting it means rewriting the GUI in GTK.
   Not recommended.

### What survives unchanged

- Hook server (`QLocalServer` works on any Qt platform).
- Settings, repo store, sidebar, theme palette, OSC *content* (escape
  sequences are display-server-agnostic; only the delivery path changes).
- `bin/claude` PATH-shadow trick (still bash, still POSIX).

### What needs rework

- `src/ui/terminal_host.py` — gutted; xterm/QProcess/XEmbed all gone.
- `src/core/x11.py` — deleted.
- `src/core/xterm_osc.py` — rewritten to write OSC to the emulator widget
  rather than `/dev/pts/N`.
- `src/main.py` — drop the `WAYLAND_DISPLAY` → `xcb` block.
- `src/core/terminal_session.py` — `_inner_command()` becomes the argv we
  hand to the embedded widget instead of arguments to xterm.

### Recommendation

Spike **termqt-pyside6** first. It is the cheapest experiment, and the
soak test (running Claude Code TUI inside it for a real session) is the
gating decision: if termqt renders the TUI faithfully, that's the path.
If it doesn't, fall back to QTermWidget and accept the GPL/binding cost,
because pyte+custom is months of work no matter how it's planned.

Land the swap behind `CCWORK_TERMINAL=xterm|termqt` so existing X11 users
keep the well-tested xterm path until the embedded widget proves itself.

---

## macOS

### What blocks ccwork today

- XEmbed: not just absent, conceptually inapplicable on Cocoa.
- `libX11`: not installed by default.
- `bin/` shell scripts: bash 3.x ships by default (4+ via Homebrew); GNU
  vs. BSD utility differences in `sed`/`grep`/`stat`.
- `XDG_RUNTIME_DIR`: not standard on macOS. The hook socket needs a new
  home (`~/Library/Application Support/ccwork/` is the convention).
- `notify-send`: doesn't exist. Replace with `osascript` or
  `terminal-notifier`.
- `.desktop` file: meaningless. Need a `.app` bundle (or, for a v0.x
  release, accept "launch from terminal" and skip the bundle).

### Candidate approaches

The terminal-widget question is identical to Wayland's — pick one widget
strategy that targets all non-X11 platforms. The macOS-specific work is
script and packaging, not architecture.

1. **Embedded terminal widget** (same termqt / QTermWidget / pyte tree as
   Wayland). On macOS, PTY allocation uses `forkpty(3)` from libutil;
   PySide6's `QProcess` does not directly expose PTY mode, so the widget
   must own the PTY (which termqt and QTermWidget already do).

2. **Reimplement `bin/` scripts in Python.** This is recommended regardless
   of OS — see the Windows section. macOS becomes "configure paths
   differently" rather than "rewrite shell scripts."

3. **Packaging.** `pyinstaller` or `briefcase` (BeeWare) to produce a
   `.app`. Defer until there is genuine macOS demand; a `pip install
   ccwork` plus a launcher script is enough for early adopters.

### What survives

- Qt UI, settings, repo store, sidebar, hook flow (with the socket path
  and notify call swapped out).

### What needs rework

- All of `bin/` (becomes Python entry points).
- `install.sh` (becomes Python or platform-conditional).
- `src/core/hook_server.py` socket-path resolution (factor out an
  `xdg.runtime_dir()` helper that knows about `~/Library/Application
  Support` on macOS).
- Notification path: `desktop_notify.py` becomes a small adapter.

### Recommendation

Sequence macOS **after** the Wayland-native widget choice has stabilized.
The terminal subsystem is the long pole; everything else is mechanical.
Don't ship a `.app` bundle for the first macOS release — let early users
install via `pip` and a shell launcher.

---

## Windows

### What blocks ccwork today

- XEmbed, X11: same as macOS, irrelevant.
- PTY model is fundamentally different: Windows uses **ConPTY** (Windows
  10 1809+) via the `pywinpty` bridge.
- Bash-script `bin/`: every script must be reimplemented (PowerShell or
  Python).
- PATH-shadow trick for `bin/claude` is fragile on Windows because
  `claude.exe` resolution rules differ; expect to wrap via a `.cmd`
  shim and a Python script.
- `XDG_RUNTIME_DIR`, `notify-send`, `~/.config`, `~/.local/share`: all
  Linux-isms with Windows-specific replacements (`%LOCALAPPDATA%`,
  toast notifications via `win10toast` or PowerShell, `%APPDATA%`).
- `QLocalServer` on Windows uses Named Pipes instead of Unix sockets;
  Qt abstracts that, but the path ("\\\\.\\pipe\\ccwork") is different
  and the hook sink must speak Named Pipes from the bash/Python side.

### Candidate approaches

1. **`pywinpty` for PTY**, paired with whichever embedded widget wins on
   Linux. <https://github.com/andfoy/pywinpty> is mature, ConPTY-backed,
   widely used (Spyder, Jupyter). License BSD-ish.

2. **Drop bash entirely.** Reimplement `bin/claude` and
   `bin/ccwork-hook-sink` as Python scripts that ship as console-script
   entry points in `pyproject.toml`. This is the same recommendation as
   macOS but more forced: there is no bash on a default Windows box.

3. **Installer.** `install.sh` becomes a Python `ccwork-install` command
   (or just instructions to run after `pip install ccwork`). No registry
   manipulation, no Start Menu entry for v0.x; rely on `pip` shims.

### What survives

- Qt UI (PySide6 is fully supported on Windows).
- Settings, repo store, sidebar, hook flow (with socket abstraction
  swapped to Named Pipes via Qt).

### What needs rework

- Everything in `bin/`.
- `install.sh` and `bootstrap.sh` (the bootstrap script likely just dies;
  `pip install` is the path).
- Hook socket path resolution.
- Notifications.
- Documentation (README screenshots, install commands).

### Recommendation

Windows is the **most expensive port and the smallest audience after
subtracting WSL users** (WSL users get the Linux build for free). Sequence
it last, behind explicit user demand. The architectural blocker is the
same as macOS — the terminal widget — so most of the heavy lifting is
shared.

---

## Sequencing

1. **Linux X11 (today).** Polish v0.1 and ship. Keep xterm+XEmbed for the
   foreseeable future — it is the most reliable terminal substrate
   available on any platform.

2. **Embedded-widget spike (1–2 weeks, gated).** termqt soak test under
   real Claude Code usage. Decision point: ship behind a flag, fall back
   to QTermWidget, or shelve.

3. **Wayland-native** (releases as a flag toggle, not a separate build).
   Once the widget passes soak, set the default based on
   `WAYLAND_DISPLAY` detection, keep xterm as opt-out.

4. **`bin/` → Python entry points.** Done before macOS or Windows; same
   work serves both. ~1 week.

5. **macOS.** Mostly mechanical after steps 2–4. Skip `.app` bundling
   for the first release.

6. **Windows.** Last. Only if there is demonstrated user demand from
   non-WSL Windows developers.

---

## Open questions to resolve before committing

- Does termqt render Claude Code's full-screen TUI faithfully? Soak test
  in a branch before any roadmap commitment.
- License posture: is GPL acceptable if QTermWidget is the only viable
  path? (Currently ccwork has no `LICENSE` constraint that would block
  GPL adoption — but it does change downstream redistribution math.)
- Do we want a single embedded-widget code path that serves *all*
  non-X11 platforms, or is X11 worth keeping forever as the "fast path"?
  Current bias: keep X11 indefinitely; embedded widget is for everywhere
  else.
- Does the hook-sink protocol need versioning before we have multiple
  socket transports (Unix socket, Named Pipe)? Probably yes — add a
  `version` field to the JSON envelope before the first non-Linux ship.

---

## Sources

- QTermWidget: <https://github.com/lxqt/qtermwidget>
- termqt: <https://github.com/TerryGeng/termqt>
- termqt-pyside6 fork: <https://github.com/Sun-ZhenXing/termqt-pyside6>
- pyte: <https://github.com/selectel/pyte>
- pywinpty: <https://github.com/andfoy/pywinpty>
- ConPTY: <https://devblogs.microsoft.com/commandline/windows-command-line-introducing-the-windows-pseudo-console-conpty/>
- Wayland XEmbed-equivalent discussion: <https://github.com/wayland-transpositor/wprs/issues/54>
- Apple `forkpty` sandboxing notes: <https://developer.apple.com/forums/thread/685544>
