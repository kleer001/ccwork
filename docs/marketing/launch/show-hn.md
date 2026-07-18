# Show HN — draft (you post this)

> **Do not post until the demo GIF is in the README and you have a couple
> of real users.** Post Tue–Thu, ~8–10am ET (a low-competition Sunday
> 6–9pm ET slot also works for niche tools). Link the **repo directly**,
> not a landing page. Paste the "maker's first comment" below *immediately*
> after posting. Reply to every comment for the first 1–2 hours — vote
> velocity in the first 15–60 minutes decides front-page ranking.
> **Never** ask anyone to upvote (vote rings are detected and penalized).

## Title options (8–12 words, neutral, factual, no hype, no exclamation)

1. `Show HN: ccwork – Run Claude Code across many git repos from one Qt GUI (Linux)`
2. `Show HN: A Qt desktop app that runs Claude Code across all your repos`
3. `Show HN: ccwork – one window of real terminals + live Claude Code status badges`

**URL:** https://github.com/kleer001/ccwork

## Maker's first comment (post immediately as a comment)

Hi HN — I built ccwork because I run Claude Code across a dozen-plus repos
at once and kept losing track of which one needed my attention.

It's a native Qt (PySide6) desktop app, not a web app. Each repo gets a
real embedded `xterm` (via XEmbed — `xterm -into <winId>`), so there's no
VT100 emulation to maintain; Qt just owns the window chrome. A sidebar
lists your repos with the current git branch and a live status badge driven
by Claude Code's Stop/Notification/hook events — so a repo that's waiting
on a permission prompt or has finished a turn is glanceable across the
whole stack. There's also a local, no-network weekly "git retro" dashboard.

Honest limitations: it's **Linux + X11 only** (Wayland works via
XWayland, because XEmbed has no Wayland equivalent). No macOS/Windows yet.
No telemetry, no network calls — the dashboard is just `git` over the repos
you already track.

Stack: PySide6, embedded xterm, a Unix-socket hook sink, ~290 tests. It
started life as a tmux wrapper and the story of why that broke is in the
repo (docs/blog). Happy to answer anything about the XEmbed approach, the
hook plumbing, or why I went native instead of Electron.

## Have ready for the thread
- The one bug that killed the tmux version (focus-racing spinner) — good
  concrete story.
- Why XEmbed over xterm.js/Electron (native look, no JS churn, real mouse).
- Why X11-only and the Wayland path.
- Roadmap: cross-platform sequencing (see `docs/roadmap-cross-platform.md`).

## After the launch
- If it flops, a single resubmission later is allowed — but not spammy
  repeated reposts.
- Fold good questions into the README FAQ.
