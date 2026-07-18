# ccwork Growth & Marketing Plan

A research-backed plan to grow ccwork. It defines what "success" means,
which metrics are real vs. vanity, how to launch, and how to sustain
momentum. Companion drafts (ready to publish — you publish them, nothing
here is posted automatically) live in [`launch/`](launch/).

> **Publishing boundary:** every post below is a *draft for you to review
> and publish yourself*. Nothing in this repo posts to Hacker News,
> Reddit, X, Discord, or any awesome-list. See
> [`launch/metrics-and-cadence.md`](launch/metrics-and-cadence.md) for a
> note on where assisted/scheduled posting could plug in later (proposed,
> not built).

---

## 1. What "success" means for ccwork

The stated goals — more stars, forks, PRs, issues, contributors — are all
worth having, but they are **not equally meaningful**, and chasing them
in the wrong order wastes effort.

**Signal ranking, weakest → strongest traction:**
stars (passive interest / bookmark) → forks (active experimentation) →
real issues (someone hit a production edge case) → PRs / contributors →
downloads / installs → **contributor retention** (people who come back).
([daily.dev on OSS metrics](https://business.daily.dev/resources/how-open-source-metrics-influence-tool-adoption/),
[ToolJet](https://blog.tooljet.com/github-stars-guide/))

- **Stars are a vanity metric.** Most people who star never install, and
  the "fake star economy" makes raw counts noisy — a CMU study found ~6M
  fake stars across 18,600+ repos, so savvy observers discount them.
  ([stateshift](https://blog.stateshift.com/beyond-github-stars/),
  [CMU study coverage](https://chatgpt.ca/blog/github-fake-stars-ai-tool-evaluation))
  Chase stars as **social proof that converts future visitors**, not as
  the scoreboard.
- **Bessemer's north star is unique monthly contributors** — they
  explicitly "pay little attention to stars." Benchmarks: ~100 unique
  monthly contributors is strong; 250+ puts you among the most active
  projects ever (<5% of the top 10,000 ever reach it).
  ([Bessemer](https://www.bvp.com/atlas/measuring-the-engagement-of-an-open-source-software-community))
- A **higher fork : star ratio signals more meaningful engagement** than
  stars alone.

**So track these for ccwork (in priority order):**
1. Release-asset / PyPI download count (the closest thing to "real users"
   for a GUI tool that can't be measured by `npm i`).
2. Returning contributors and **time-to-second-PR**.
3. Issue quality (real bug reports with distro/X11/xterm detail).
4. Discord members / Discussions participants as a proxy for active users.
5. Stars — as social proof, watched but not optimized for.

See [`launch/metrics-and-cadence.md`](launch/metrics-and-cadence.md) for
the tracking setup.

---

## 2. Positioning

**One-liner:**
> **ccwork — run Claude Code across all your repos from one window. Real
> embedded terminals, a clickable repo sidebar, and live status badges
> driven by Claude Code's hooks.**

**Who it's for:** developers who run Anthropic's Claude Code heavily across
*many* repositories at once, on Linux. That specificity is a feature —
"vague, blazing-fast, modern" positioning underperforms concrete
positioning.
([markepear](https://www.markepear.dev/blog/dev-tool-hacker-news-launch))

**Honest limitation, stated up front:** Linux + X11 only (Wayland via
XWayland). Leading with the constraint builds trust on HN/Lobsters and
filters for the right audience.

**Why it's different (lead with these):** the Claude-Code-specific value —
multi-repo orchestration and live hook status badges — is what the Claude
ecosystem lists explicitly favor.

---

## 3. The repo IS the landing page

Developers decide "is this worth using" in ~15–30 seconds, so repo
presentation is conversion, not decoration.

- **A demo GIF at the top of the README is the single highest-ROI asset.**
  Projects with a demo GIF average ~40% more stars, and for a *GUI* tool
  it's doubly true — a clip showing the sidebar, embedded xterms, and hook
  badges lighting up sells ccwork better than any paragraph.
  ([rekort](https://rekort.app/blog/gif-for-github-readme),
  [dev.to README best practices](https://dev.to/iris1031/github-readme-best-practices-how-to-write-a-readme-that-gets-stars-2gb2))
  → Build it first. Shot list: [`launch/demo-shotlist.md`](launch/demo-shotlist.md).
- **Above-the-fold order that converts:** (1) one concrete sentence;
  (2) hero image; (3) demo GIF; (4) a copy-paste quickstart that works on
  the first try, in the first ~200 words; (5) **3–4 functional badges
  only** (build, version, license, Discord) — long "vanity badge walls"
  now read as filler.
  ([gingiris](https://gingiris.tools/blog/2026/04/02/github-readme-template-guide/))
- **GitHub repo topics** (free, passive, ongoing discovery): add
  `claude-code`, `claude`, `claude-code-hooks`, `python`, `pyside6`,
  `linux`, `developer-tools`. People browse
  [github.com/topics/claude-code](https://github.com/topics/claude-code)
  to find exactly this.
- **Community-health files** (now added): `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue/PR templates. ccwork went
  from ~2/7 to ~6–7/7 on GitHub's community-standards checklist. These
  auto-surface at the moment intent peaks (new issue / new PR).
  ([GitHub community profiles](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories))

---

## 4. Launch sequence

The launch is a **spike**; distribution + cadence is the **engine**. Do
these roughly in order — don't fire the big channels before the demo GIF
exists.

1. **Polish the README + record the demo GIF.** Prerequisite for
   everything else.
2. **Add GitHub topics** (above).
3. **Soft-share** in the Claude Discord showcase channel and **r/ClaudeAI**
   ("I built X for Claude Code" show-and-tell) — your highest-signal
   niche. Gather a few early users + stars first; curated lists expect it.
4. **Show HN** — the single highest-leverage launch. Tue–Thu, ~8–10am ET;
   neutral factual title, 8–12 words; link the repo directly (not a
   landing page); post a maker's-first-comment immediately; **reply to
   every comment in the first hour** (vote velocity in the first 15–60 min
   drives ranking).
   ([Show HN guidelines](https://news.ycombinator.com/showhn.html),
   [Flowjam playbook](https://www.flowjam.com/blog/how-to-get-on-the-front-page-of-hacker-news-in-2025-the-complete-up-to-date-playbook))
   Draft: [`launch/show-hn.md`](launch/show-hn.md).
5. **Publish a dev.to build write-up** the same day (repurpose
   [`../blog/from-session-manager-to-desktop-app.md`](../blog/from-session-manager-to-desktop-app.md)).
   Draft: [`launch/devto-article.md`](launch/devto-article.md).
6. **Submit to awesome-claude-code** once you have early stars — via its
   **web issue-form template, NOT a PR/CLI** (submitting the wrong way
   risks being restricted).
   ([awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code))
   Draft: [`launch/awesome-claude-code-submission.md`](launch/awesome-claude-code-submission.md).
7. **Reddit, spaced out** — r/commandline, r/selfhosted (Product
   Announcement flair), r/Python (Showcase flair), each with framing
   tailored to that sub, **days apart** (never identical simultaneous
   cross-posts). Drafts: [`launch/reddit.md`](launch/reddit.md).

**Realistic horizon:** a well-executed launch buys the first burst of
stars fast; the long tail comes from months of content, releases, and
community. ([AFFiNE case study](https://dev.to/iris1031/how-to-get-more-github-stars-the-definitive-guide-33k-stars-case-study-2kjo))

---

## 5. Channel fit (quick reference)

| Channel | Fit | Notes |
|---|---|---|
| **Show HN** | ★★★ | Highest leverage. Tue–Thu AM ET, factual title, camp comments. |
| **r/ClaudeAI** | ★★★ | Best Reddit fit — your exact audience. Show-and-tell, genuinely useful. |
| **Claude Discord showcase** | ★★★ | Ideal users gather here. Post in showcase, not general. |
| **awesome-claude-code** | ★★★ | Durable, compounding discovery. Submit via **web issue form**. |
| **GitHub topics** | ★★☆ | Free passive discovery; set once. |
| **r/commandline** | ★★☆ | Loves clean demo GIFs; low tolerance for pure marketing. |
| **r/selfhosted** | ★★☆ | "Product Announcement" flair; strong for a self-hostable Linux tool. |
| **dev.to / Hashnode** | ★★☆ | Technical article, not an ad. Repo link at the end. |
| **Lobsters** | ★★☆ | Invite-only; high signal; must participate, not drive-by. |
| **r/Python / r/programming** | ★☆☆ | Big but conservative; use Showcase flair / weekly threads. |
| **Product Hunt** | ★☆☆ | Skews polished SaaS; weaker fit for a Linux-only CLI-adjacent GUI. |
| **X / build-in-public** | ★★☆ | Short clips of the multi-repo dashboard; native video beats links. |

---

## 6. Contribution funnel (turn users into contributors)

Stars come from presentation + reach; **forks/PRs come from the code being
easy to run, hack, and contribute to**.

- **Curate 5–10 genuinely stranger-scoped `good first issue` /
  `help wanted` issues.** The backlog is the work; the label is trivial —
  and labels are worthless without real issues behind them. This makes
  ccwork appear in GFI aggregators (github-help-wanted.com,
  firsttimersonly.com). Candidates:
  [`good-first-issues.md`](good-first-issues.md).
  ([GFI longitudinal study](https://arxiv.org/pdf/2604.27532),
  [firsttimersonly](https://www.firsttimersonly.com/))
- **Respond fast.** Contributors who get quality feedback within 24h are
  ~3× more likely to contribute again; responsiveness is the strongest
  retention lever.
  ([count.co](https://count.co/metric/open-source-contribution-analysis))
- **Signal openness.** `CONTRIBUTING.md` + `CODE_OF_CONDUCT` tell strangers
  "PRs welcome"; their absence reads as "solo, don't bother." (Done.)
- **Lean into Claude-Code-friendliness.** ccwork's `CLAUDE.md` already
  helps AI-assisted contributors; `CONTRIBUTING.md` now says so explicitly.
  Much of this ecosystem's contribution is AI-assisted.
- **Enable GitHub Discussions** (a repo-settings toggle) as a low-stakes
  on-ramp, and consider **all-contributors** to credit non-code work.

---

## 7. Sustain: cadence beats intensity

You cannot sustain the launch spike — you sustain a cadence.
([dev.to: 9 levers](https://dev.to/iris1031/github-star-growth-9-levers-that-compound-in-2026-15d))

- **~1 content piece per week** — a tutorial, a "how I use Claude Code
  across 20 repos" post, or a milestone write-up. It compounds over months.
- **Regular releases** with a short `CHANGELOG.md` entry + a fresh demo
  clip signal "alive." Re-launch major milestones (v1.0, big features) as
  a *second* Show HN — returning visitors convert.
- Full rhythm + what to measure:
  [`launch/metrics-and-cadence.md`](launch/metrics-and-cadence.md).

---

## Sourcing note

Several statistics here (e.g. "~40% more stars from a GIF," "1.4 stars per
HN upvote") come from single practitioner blogs and should be treated as
**directional benchmarks**, not peer-reviewed facts. The most rigorously
grounded claims are the Bessemer contributor benchmarks, the CMU fake-star
study, and the GFI academic studies. All URLs are inline above.
