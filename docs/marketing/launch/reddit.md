# Reddit — drafts (you post these)

> **Golden rule:** most of your account activity must be genuine
> participation, not self-links (the informal 90/10 rule). Read each
> subreddit's sidebar/wiki rules first — they're mod-enforced and vary.
> **Space these out over days/weeks. Never post the identical title+link
> to multiple subs at once** — simultaneous cross-posting is the #1
> trigger for spam filters and shadowbans. Vary the framing per community
> and reply to comments.

---

## r/ClaudeAI — best fit, post first

**Flair:** check pinned rules for a "show and tell" / project flair.

**Title:** I built a Linux desktop app to run Claude Code across all my
repos in one window

**Body:**
I kept running Claude Code in a bunch of separate terminals across
different projects and losing track of which one needed me. So I built
**ccwork**: a Qt desktop app with a sidebar of repos, a real embedded
terminal per repo, and live status badges wired to Claude Code's hooks —
so "waiting on a permission prompt" or "turn finished" is glanceable across
every repo at once. It also has a local weekly git-activity dashboard.

Native Qt, no Electron, no telemetry. **Linux + X11 only** for now
(Wayland via XWayland). MIT-licensed. Would love feedback from other
heavy Claude Code users — especially on what multi-repo workflows you'd
want it to support.

Repo: https://github.com/kleer001/ccwork

---

## r/commandline — post a few days later

**Culture:** rewards a clean demo GIF / asciinema and a genuine "I made
this" story; low tolerance for pure marketing.

**Title:** ccwork — embedding real xterms in a Qt window to manage many
terminals at once

**Body:**
Lead with the demo GIF. Focus on the *terminal* angle: each repo gets a
real `xterm` reparented into the Qt window via XEmbed (`xterm -into
<winId>`), resized in lockstep so the PTY gets `SIGWINCH` — no VT100
emulation. It happens to be built for Claude Code, but the embedding
technique is the interesting part for this crowd. X11/XWayland only.
Repo + write-up linked. Happy to go into the XEmbed details.

---

## r/selfhosted — optional, post later

**Flair:** use the **"Product Announcement"** flair (required for
self-promo here).

**Title:** ccwork — self-hostable Qt dashboard for running Claude Code
across your repos (Linux, MIT)

**Body:** Emphasize local-only / no-network / no-telemetry and MIT. Short,
factual, with the GIF. Engage in the comments — that's what converts here.

---

## r/Python — optional, use the Showcase flair or weekly thread

**Title:** ccwork: a PySide6 desktop app that embeds real xterms and reacts
to Claude Code hooks

**Body:** Python-angle framing — PySide6, `QAbstractListModel` sidebar,
XEmbed via ctypes/libX11, a `QLocalServer` hook sink, ~290 tests with an
offscreen-Qt CI. Repo link at the end. r/Python is conservative on
promotion; prefer the "Showcase" flair or the weekly "what are you working
on" thread over a standalone post.

---

## Anti-patterns (will get you removed/banned)
- Identical simultaneous cross-posts across subs.
- Posting from a brand-new zero-karma account.
- Drive-by posting with no comment engagement.
- Salesy, adjective-heavy titles in strict subs (r/linux, r/programming).
