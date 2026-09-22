# Ideas to borrow from throng

**Source:** [Bidthedog/throng](https://github.com/Bidthedog/throng), version
`1.0.0-beta7`, commit `e72f6d7c826c9250b8ebec8d4947ff20e9b9d96f`.

throng is a Windows-only Electron/TypeScript workspace for running many terminals
across isolated projects. It runs `claude` inside its terminals but has no
hook-based status integration. Its terminals are `node-pty`/ConPTY processes owned
by a **detached background daemon**, so they survive a UI restart and reattach.

ccwork embeds real `xterm` processes via XEmbed and reads Claude Code hooks for
live per-repo status. The two apps solve the same problem from opposite ends, so
most borrowing runs throng → ccwork on process durability and hygiene.

File paths below are relative to the throng repo at the commit named above.

---

## 1. Detached PTYs that survive a UI restart, with scrollback replay

**throng:** terminals run in a daemon process, not the UI. Closing the window
leaves them running; reopening reattaches and replays a bounded scrollback tail.

- `packages/daemon/src/terminal-service.ts` — per-session scrollback buffer
  (`MAX_SCROLLBACK = 64 * 1024`), reattach path, replay-into-new-view logic.
- Alt-screen guard: a program on the alternate screen (a live TUI) gets **no**
  replay — replaying cursor moves paints stale output. The scrollback is withheld
  from that view, not discarded; a later attach after the program leaves the alt
  screen gets it.

**ccwork today:** xterms die with the app. Only the Claude *conversation* is
recovered, via `claude --resume` (`src/core/session_recovery.py`). The live PTY,
scrollback, and shell state are lost.

**Adoption note:** large lift under XEmbed — xterm cannot reparent into a dead
process, so this needs a separate process owning the PTY. The alt-screen replay
rule is a cheap, standalone win if any replay is ever added.

## 2. Startup orphan reaper with PID-reuse detection

**throng:** a fresh daemon sweeps for orphaned child processes at startup, as a
backstop for the case where a hard kill skipped cleanup.

- `packages/daemon/src/reap-orphans.ts` — pure `findOrphans(procs, selfPid)`.
- An orphan is a throng-owned process whose parent is gone: either no process
  holds its `ParentProcessId`, or one does but **started after the child** (the
  PID was reused, so the real parent is dead). This never reaps a live parent's
  children, so it is safe with concurrent instances.

**ccwork relevance:** ccwork spawns xterms and recently fixed stray-xterm restore
(commit `a77dcbb`, `SESSION_MANAGER` unset). A startup sweep for xterms orphaned
by a crashed prior ccwork is the same class of hygiene. The PID-reuse check is the
part worth copying exactly.

## 3. Auto-recover a terminal when its working directory reappears

**throng:** a terminal that failed because its working directory was missing arms
a watch on the nearest existing ancestor and restarts when the directory returns.

- `packages/core/src/terminal/reconnect.ts` — pure rules:
  - `shouldWatchForRecovery` arms **only** for `path-missing`, not for a bad shell
    binary or a permission denial (a directory watch cannot observe an ACL change).
  - `watchTargetFor` walks up to the nearest ancestor that exists, since a watch
    needs an existing target.
  - `reconnectsReleasedBy` releases a pending reconnect only when it is the same
    project **and** the target now resolves — so a sibling folder appearing under
    a shared parent does not thrash every waiting terminal.

**ccwork today:** a renamed/deleted `repo.path` paints `(path missing)` in the row
sub-line (`ROLE_PATH_MISSING` in `RepoListModel.refresh_branches`) and stops
there; recovery is the manual *Rebind to…* action.

**Adoption note:** ccwork already has the failure state and the branch-refresh
sweep. Adding a path-return watch turns the dead `(path missing)` row into
self-healing. Keep throng's per-project scoping and the "target must now resolve"
filter.

## 4. Per-area specialist subagents with a routing table

**throng:** `.claude/agents/` holds one subagent per subsystem, each carrying that
area's file map, rules, and known traps, plus a README routing table and a
skill-vs-agent precedence rule (skill wins on process, agent owns area knowledge).

- `.claude/agents/README.md` — the routing table and the maintenance rule ("an
  agent file is only worth its context if it is true; update it when the area's
  rules change").

**ccwork relevance:** aligns with the standing goal of splitting large multi-class
files. A per-area agent map is a low-cost step toward that structure and gives a
subagent a place to start instead of re-deriving a subsystem each time.

---

## What ccwork already does that throng does not

Do not borrow backward here — record it so the borrow direction stays clear.

- **Hook-driven live status:** working spinner, done/attention badge, subagent
  twinkle, live-session grouping. throng runs `claude` but reads no hooks.
- **Crash recovery to `claude --resume`** from a per-session snapshot.
- **Weekly-retro dashboard** on the splash.

## Not worth borrowing at ccwork's size

- **Spec Kit** (`specs/NNN-*/spec.md` with FR traceability) and the eight-stage
  remote `gate.yml` CI. throng-scale process for a beta with a release pipeline;
  overkill for ccwork. throng's `CLAUDE.md` writing discipline is still a good
  model — "the gate is the only done-ness", citation accuracy, "one condition,
  one notice".
