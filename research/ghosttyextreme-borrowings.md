# Ideas to borrow from GhosttyEXTREME

**Source:** [steventsvik/GhosttyEXTREME](https://github.com/steventsvik/GhosttyEXTREME),
tag `extreme-1.5.5.1`, commit `377733dfab786ace29d8bfb30bec7782c06c5559`
(based on Ghostty 1.3.1).

GhosttyEXTREME is a macOS-only (Apple silicon) fork of the Ghostty terminal, built
for watching coding agents. Its own code is Swift in `macos/Sources/Features/` plus
shell and Python hooks in `agent-hooks/`. Its scope is much wider than ccwork's: a
Monaco editor that follows the agent, a code map, a review inbox, backend and
database views, agent races, Docker sessions. Most of that is out of scope for
ccwork. The ideas below are the ones that touch the same problem ccwork solves:
live per-agent status from Claude Code hooks.

The core design difference: GhosttyEXTREME **is** the terminal emulator, so it owns
the screen and the PTY. ccwork embeds external `xterm` processes via XEmbed and
owns neither. Several features below follow directly from that difference.

File paths below are relative to the GhosttyEXTREME repo at the commit named above.

---

## 1. Per-terminal event routing

**GhosttyEXTREME:** hooks do not use a socket. `agent-hooks/agent-hook.sh` builds an
OSC 777 escape sequence and returns it in the Claude Code hook output field
`terminalSequence`; Claude Code writes it to its own terminal. The app reads the
sequence out of that pane's output stream, so every event arrives already bound to
one pane. State is keyed by pane (`Vertical Tabs/VerticalTabsAgents.swift`,
`NSMapTable<SurfaceView, Box>` with weak keys), and closing a pane drops its state.

**ccwork today:** events carry only `cwd`. State is path-keyed and broadcast to
every row on that path. Session liveness is tracked per `session_id`, but spinner
and DONE / ATTENTION state cannot tell two rows on one path apart.

**Adoption note:** ccwork does not need the escape-sequence transport. It spawns
each xterm itself, so it can put a row identifier in each xterm's environment and
have `bin/ccwork-hook-sink` copy it into every event. The socket stays; the routing
key changes from path to row.

## 2. Agent-exit detection from the shell

**GhosttyEXTREME:** `agent-hooks/ghostty-extreme.zsh` uses zsh `preexec` / `precmd`
to mark a pane when a known agent command starts and to clear the mark when the
command returns, whether the agent quit cleanly, crashed, or used `/exit`.

**ccwork today:** Claude Code sends no `SessionEnd` hook for `/exit`
(anthropics/claude-code#17885). ccwork falls back to clearing session state when
the row's xterm process exits, which misses an `/exit` that leaves the shell open.

**Adoption note:** ccwork already owns the `claude` entry point (`bin/claude`, a
`PATH` shadow that `exec`s the real binary). Running the real binary as a child and
sending an exit event when it returns gives the same signal without shell hooks.

## 3. Turn checkpoints with git tree objects

**GhosttyEXTREME:** at the start of each agent turn it snapshots the working tree
without touching the repository's refs, commits, stash, or real index
(`Review/ReviewInbox.swift`, `snapshot`; `Review/TurnCheckpoints.swift`):

1. Copy the real index to a temporary file (keeps git's stat cache, so only
   changed files are hashed).
2. `GIT_INDEX_FILE=<temp> git add -A`, then `git write-tree`.
3. Keep the tree SHA, up to 30 per pane.

Restoring first takes a new snapshot, so a restore can itself be undone. Plain
folders use a private shadow repository.

**Adoption note:** pure git, no Qt. Small enough to live in `src/core/`.

## 4. Failed-turn state

**GhosttyEXTREME:** installs the `StopFailure` hook (a turn ended on an API error)
and shows a distinct error state.

**ccwork today:** does not install `StopFailure`. If `Stop` does not also fire on an
API error, the working spinner keeps running after the turn has ended.

## 5. Notification types

**GhosttyEXTREME:** maps `notification_type` from the `Notification` payload:
`permission_prompt` → needs permission, `elicitation_dialog` → needs input. Every
other type is ignored (`agent-hooks/agent-hook.sh`, the `$e` mapping).

**ccwork today:** installs `Notification` with matcher `"*"` and sets ATTENTION on
every type. Claude Code documents many types besides prompts, including
`idle_prompt`, `auth_success`, and `quota_*` notices, so a finished row can turn
red when nothing needs the user. The hook matcher filters on `notification_type`.

## 6. Answering a permission prompt from outside the terminal

**GhosttyEXTREME:** Allow / Deny buttons on the sidebar card, in Mission Control,
and on the desktop notification (`Vertical Tabs/AgentPermissions.swift`). Before
it sends a key, it parses the bottom of the pane's screen and requires the prompt,
with "1. Yes" selected, to be visible. Escape interrupts a working agent and Enter
submits typed text, so a stale "waiting" state must never send a key.

**Adoption note:** ccwork cannot read an xterm's screen (see Gaps). The Claude Code
`PermissionRequest` hook can return an `allow` / `deny` decision directly, which
avoids screen parsing. How the in-terminal dialog behaves while a hook blocks is
not documented; test before building on it.

## 7. Hidden work stops

**GhosttyEXTREME:** every endless animation pauses for background tabs and hidden
or minimized windows (`CLAUDE.md`, "Performance rules").

**ccwork today:** `_spinner_timer` in `src/ui/repo_sidebar.py` runs while any repo
is working, whether or not the window is visible.

---

## Where ccwork is ahead

- **Event authenticity.** ccwork's socket lives under `$XDG_RUNTIME_DIR`, readable
  only by the user. GhosttyEXTREME's OSC events can be imitated by any printed text,
  so it adds a per-launch secret to every event (`Vertical Tabs/EventToken.swift`)
  and is capped at a 255-byte event body.
- **Subagents.** ccwork counts subagents and paints a separate badge.
  GhosttyEXTREME registers subagent hooks but drops them for Claude.
- **Crash recovery.** ccwork records open sessions on disk and offers
  `claude --resume` after an unclean shutdown. GhosttyEXTREME offers resume only
  from its activity history.

## Gaps that follow from embedding xterm

- **No screen access.** xterm owns the PTY master and XEmbed exposes no screen
  text. Live output tails, prompt checks before sending keys, and per-command
  blocks all need the screen. Closing this gap means replacing xterm with an
  emulator ccwork drives itself.
- **No input path through the PTY slave.** Data written to `/dev/pts/N` from
  outside is terminal *output*: it reaches the master (xterm's display), not the
  shell's input, and control bytes such as `0x1a` raise no signal. Input must go
  through X (XTest or `XSendEvent` to the focused xterm), and signals must go
  directly to the foreground process group (`tpgid`, field 8 of
  `/proc/<shell-pid>/stat`).
