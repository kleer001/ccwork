# Demo GIF/video shot list — build this FIRST

The demo is ccwork's single highest-ROI asset and a prerequisite for
almost every channel. It's what HN, Reddit, and awesome-list reviewers
judge first. Because ccwork is a **GUI**, a screen-capture GIF/MP4 of the
window beats asciinema (which can't capture the Qt chrome).

## Tools (Linux)
- **GUI capture:** [Peek](https://github.com/phw/peek) (simple GIF
  recorder) or **OBS Studio** (MP4, then convert). GitHub also accepts
  drag-and-dropped **MP4** in READMEs for a longer clip.
- **Terminal-only insets (optional):** [VHS](https://github.com/charmbracelet/vhs)
  (scriptable `.tape` files, reproducible) or asciinema + `agg`/`svg-term-cli`.
- **GIF specs:** ~12 FPS, keep it **under ~5 MB** so the README loads fast.
  Store at `docs/images/demo.gif` (that dir now exists for exactly this).

## The 15–25 second sequence (one task, readable pace)
1. **Open on the window** — sidebar of 4–6 repos, each with branch +
   ambient badge. (1–2s)
2. **Click a repo** → its embedded terminal appears; start a Claude Code
   turn in it. (3–4s)
3. **Switch to a second repo**, start a turn there too — show two real
   terminals coexisting. (3–4s)
4. **The payoff: badges light up** — a working spinner on one row, a green
   DONE dot on another, a red attention dot on a third (permission
   prompt). This is the whole pitch: glanceable multi-repo status. (4–6s)
5. **Click the Dashboard slot** → the weekly git-retro splash (trend chart
   + radar fingerprints). (3–4s)
6. **End on the full window** so the last frame is a clean hero shot. (1s)

## Framing tips
- Use a clean theme and a legible font size; hide personal paths.
- Type at a readable speed; don't rush the badge moment — it's the point.
- The **badge-lighting-up moment** is the money shot; make sure it's
  unmistakable.

## Where it goes
- Top of the `README.md` (right after the one-line description).
- Same asset embedded in the dev.to article and shared natively on X.
- A longer 2–5 min YouTube walkthrough ("how I run Claude Code across all
  my repos") is high long-tail value — lower urgency than the GIF, but
  embeddable everywhere afterward.

## README placement note
Add descriptive **alt text** and a "prefers-reduced-motion → static
screenshot" fallback (see good-first-issue #9) for accessibility.
