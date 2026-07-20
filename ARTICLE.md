# Don't try to make this in a terminal multiplexer like Tmux or Zellij

ccwork is a Qt desktop app that runs several `claude` sessions side by side,
one per repository, and paints the live state of each one — working, waiting
for permission, done, running subagents — in a sidebar. The obvious first
instinct for a tool that "shows a bunch of terminals at once" is a terminal
multiplexer: tmux, GNU screen, Zellij, or the wezterm mux. That instinct is
wrong here, and the reasons are structural, not stylistic.

## The reasons

**A multiplexer multiplexes text. This app needs a window.**

The terminals in ccwork are real `xterm` processes, embedded into the GUI via
XEmbed with `xterm -into <winId>`. The Qt widget owns a native X window, xterm
is reparented into it, and the two are resized in lockstep so the PTY gets
`SIGWINCH`. There is no Wayland equivalent, which is why the app forces
`QT_QPA_PLATFORM=xcb` and is Linux + X11/XWayland only. A multiplexer gives you
panes inside one terminal grid; it does not give you a window you can draw
pixels into next to those panes. Everything below depends on having that
window.

**The status surface is graphical, per-repo, and animated.**

Each sidebar row carries state a status line can't express: an animated braille
working spinner (one of five variants, chosen per repo so it's stable across
launches), a red attention dot when a session hits a permission prompt, a green
done dot after a turn ends, a left-edge subagent "twinkle" that pulses while
background agents run, and an ambient glyph that switches from a bare-terminal
mark to a "Claude is here" mark on session start. These are colored, layered
(two right-edge badge slots plus a left-edge stripe), and they animate on
independent clocks. A tmux status line is one row of text.

**State comes from Claude Code hooks over a socket, not from scraping output.**

ccwork doesn't guess what a session is doing by reading its scrollback. Claude
Code hooks (`UserPromptSubmit`, `Stop`, `Notification`, `PreToolUse`,
`SubagentStop`, `SessionStart`, `SessionEnd`) are wired to a sink that writes
one JSON line per event to a Unix socket, which a `QLocalServer` inside the GUI
turns into signals that drive the row state. That event-to-state machine —
which session is live, which is working, how many subagents are in flight — has
no natural home in a multiplexer. It needs a process that owns the socket, the
window, and the model behind the rows.

**Keyboard handling fights the terminal, and wins at the X-server level.**

Because the embedded xterm is not a Qt widget, when it holds X input focus Qt's
normal shortcut chain never sees a keypress. The fix is a passive `XGrabKey` on
the app's own X window plus one native event filter, intercepting combos at the
X-server level before xterm can consume them — scoped to ccwork's focus chain
so the shortcuts don't leak into other applications. This is the opposite of how
a multiplexer works, where the mux is the thing eating your keys.

**The rest is GUI, full stop.**

A weekly-retro dashboard with an 8-week commit trend chart and per-repo radar
fingerprints. A crash-recovery banner that lists the Claude sessions open when
the app died, each with Copy and Launch buttons. An emoji badge picker. A recent
-repo recall popup. Desktop notifications. None of these are text; all of them
need the window.

## The dogfooding, layer by layer

The features didn't land as a plan. They landed in waves, each one added while
using the tool, then hardened when the use exposed a problem.

**Keybindings, and then keybindings scoped.** The first wave replaced Qt's
`QAction` shortcuts with the root-window `XGrabKey` approach so hotkeys would
fire even while xterm held focus. Using it immediately surfaced the bug: a root
grab is system-global, so `Ctrl+Shift+P` and `Ctrl+Tab` were cycling repos and
popping dialogs while the user was in Firefox. The follow-up moved the grab from
the X root to the app's own window, scoping the shortcuts to ccwork's focus
chain — and that scoping became the load-bearing regression guard the live test
suite exists to protect.

**Window ergonomics.** Persisted and restored window size, position, and
maximize state. A working-count suffix in the title bar. Per-turn elapsed time
in the working-row tooltip. Row-jump feedback in the status bar. An empty-state
placeholder with a logo and hints. An F1 keyboard cheatsheet. Small things, each
one added because the daily use made its absence obvious.

**Refactors under load.** As features stacked, `main_window.py` and
`repo_sidebar.py` grew. The sidebar was split into four modules — model,
delegate, theme, widget — the 1813-line file broken up without changing
behavior. The main window had its bell button, terminal menu, and key bindings
extracted. Persist, grab, and test-fixture boilerplate was deduplicated. This is
the maintenance layer that made the later features cheap.

**Terminal correctness.** Opting xterm out of X11 session management. Warning
before `Ctrl+C` reaches the foreground process, and copying selections to the
clipboard on highlight. Distinguishing a missing repo directory from a detached
HEAD, with a "Rebind to…" action to repoint the row.

**The badge and subagent layer.** Badge glyphs, colors, and labels moved into a
config-driven theme module overridable by a `badges.toml`. The subagent twinkle
was wired to fire on `Task`/`Agent` dispatch and to keep painting until each
`SubagentStop` arrived. The spinner and twinkle got clear-on-exit handling so a
terminal closing didn't leave them animating forever.

**The splash became a dashboard.** First a live git-pulse bento — a week's
commit total, a bar chart, repos with uncommitted changes, the most recent
commit — with stats gathered off the GUI thread so git forks never blocked the
UI. Then that was replaced with a full weekly-retro dashboard: a narrative
sentence, an 8-week trend hero, per-repo radar fingerprints normalized to the
busiest repo, a release callout, all on rolling 7-day windows re-swept every 60
seconds because the board claims to be live.

**Recovery and resilience.** A crash-recovery banner that remembers which Claude
conversations were open when the app died and offers them back with Copy and
Launch buttons — handing the resume command to the shell via history rather than
blind-typing into a half-booted PTY. A fix so one session's `SessionEnd` doesn't
wipe a sibling session's live working spinner on the same repo. A refusal to
steal the hook socket from an already-running instance, which would otherwise
leave the first instance permanently deaf.

**The tail of the stack.** A recent-repo recall slot and a Dashboard slot at the
bottom of the sidebar, then the v0.2.0 release.

Every one of these is either a graphical surface, a hook-driven state change, an
X-server-level input grab, or a window the app draws into. A multiplexer gives
you none of the four.
