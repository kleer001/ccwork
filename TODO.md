# TODO

Pending work and decision points. Authoritative detail lives in the
linked documents under `docs/`; this file is the index.

## Ship v0.1.0

Walk [`docs/release-checklist.md`](docs/release-checklist.md) end to end.
Pre-flight (tests green, CI green, version bump in `pyproject.toml` +
`src/__init__.py`, doc skim) is mechanical and local. Fresh-machine
smoke needs a throwaway Linux VM with `xterm`. Tag + GitHub release
follow.

## Cross-platform port

Sequencing is set in
[`docs/roadmap-cross-platform.md`](docs/roadmap-cross-platform.md). The
next concrete step after v0.1 ships:

- **termqt-pyside6 soak test** — does it render Claude Code's full-screen
  TUI faithfully? Spike under a `CCWORK_TERMINAL=termqt` flag and decide:
  ship behind the flag, fall back to QTermWidget, or shelve. This is the
  gating decision for everything below.

After the widget choice stabilizes:

1. Wayland-native (flag toggle, xterm stays as opt-out).
2. `bin/` shell scripts → Python entry points (serves macOS and Windows
   both; ~1 week).
3. macOS — mostly mechanical after step 2; skip `.app` bundling for the
   first release.
4. Windows — last, only on demonstrated non-WSL demand.

## Specs

Built. Each spec records the design behind the code.

- [`row-routing.md`](docs/specs/row-routing.md) — route hook events to the terminal's row, and rebind a row when its terminal starts Claude in another repo.
- [`row-titles-and-layout.md`](docs/specs/row-titles-and-layout.md) — the three-line row, the title synced with Claude's session title, `ccwork-rename`, and the status text.
- [`hook-events.md`](docs/specs/hook-events.md) — StopFailure, PermissionRequest, SubagentStart, compaction, and a badge for each stop reason.
- [`claude-exit.md`](docs/specs/claude-exit.md) — a `ClaudeExited` event from `bin/claude`.
- [`idle-row-expiry.md`](docs/specs/idle-row-expiry.md) — remove rows that have been idle for N days.
