# Metrics & cadence

## What to track (in priority order)

Stars are social proof, not the scoreboard. Track traction:

1. **Installs / downloads** — the closest proxy to "real users" for a GUI
   tool. Options: publish release assets (a tagged GitHub Release) and
   watch download counts, and/or publish to **PyPI** and track download
   stats (pypistats). This is the most honest signal ccwork can get.
2. **Returning contributors & time-to-second-PR** — the strongest health
   signal in the research. One repeat contributor > 100 drive-by stars.
3. **Issue quality** — real bug reports carrying distro / X11-vs-XWayland /
   xterm version (the templates now prompt for these).
4. **Community size** — Discord members / GitHub Discussions participants
   as a proxy for active users.
5. **Fork : star ratio** — a rising ratio means people are actually
   experimenting, not just bookmarking.
6. **Stars** — watch the trend (star-history.com) as social proof; don't
   optimize for the raw number.

Set a simple monthly check: downloads, new vs. returning contributors,
open-issue response time (aim <24h — the single biggest retention lever),
Discussions/Discord growth.

## Weekly cadence (the engine)

The launch spike fades within a week; a steady cadence compounds over
months.

- **~1 content piece / week** — a tutorial, a "how I use Claude Code across
  N repos" post, a milestone write-up, or a short build-in-public clip on X.
- **Regular releases** — each with a `CHANGELOG.md` entry and a fresh demo
  clip. "Consistency beats intensity: a weekly update with a fresh demo
  clip out-performs a single viral post over a year."
- **Re-launch milestones** — v1.0 and big features get a *second* Show HN
  and a fresh Reddit/dev.to round. Returning visitors convert to stars.
- **Respond fast** to every issue/PR — this is contributor retention.

## Automation — proposed, NOT built (per "discuss later")

Everything above is drafted for **you to publish manually**. If you later
want assistance, the lowest-risk, human-in-the-loop options — none of
which auto-publish — are:

- A **scheduled draft-generator**: on each new release tag, an agent drafts
  the release-note post + changelog blurb + a short X clip caption and
  leaves them for your approval. (Could be wired as a Routine / cron that
  opens a draft, never posts.)
- A **metrics digest**: a weekly local script that pulls stars/downloads/
  open-issue-age into a one-screen summary so the monthly check is trivial.
- A **"stale issue/PR" nudge** that flags anything past your response-time
  target.

Recommendation: keep **all public posting manual** for the foreseeable
future — HN/Reddit/Discord/awesome-lists all penalize anything that reads
as automated, and the trust cost of a bot misstep in these communities is
high. Automate *drafting and measurement*, never *posting*. Revisit once
there's a steady release rhythm worth scripting around.
