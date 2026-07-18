# dev.to / Hashnode build write-up — draft (you publish this)

> Works as a **technical story**, not a launch ad. Publish the same day as
> Show HN, link the repo at the end. Tags: `#python #linux #ai #opensource`.
> On Hashnode, set the canonical URL to the dev.to post to avoid SEO
> duplication.
>
> **Source material already exists:** most of this is
> [`../../blog/from-session-manager-to-desktop-app.md`](../../blog/from-session-manager-to-desktop-app.md)
> (the moved `mediumarticle.md`). Reuse it — it already tells the
> tmux-spinner-bug → desktop-app story, which is exactly the arc dev.to
> readers reward.

## Suggested title
**The bug that turned my Claude Code session manager into a desktop app**

## Structure
1. **Hook (the bug):** the braille spinner that renamed the *wrong* tmux
   tab because rename targets the focused tab, not the calling process's
   tab. (Already written in the blog draft.)
2. **The realization:** the terminal multiplexer was the wrong substrate —
   no clickable repo list, no stable header, transient toasts.
3. **The rewrite:** native Qt owning the chrome; embedding real `xterm` via
   XEmbed instead of emulating VT100; forcing `xterm` under XWayland so
   reparenting works.
4. **The interesting engineering:** XGrabKey on `self.winId()` (not the
   root) to scope shortcuts to ccwork's focus chain; the hook sink over a
   Unix socket; the path-keyed state model that lets several `claude`
   sessions share a repo dir.
5. **What it looks like now:** embed the demo GIF here too.
6. **Honest limits + roadmap:** X11-only, Wayland via XWayland, cross-
   platform sequencing.
7. **CTA:** repo link, "good first issues" pointer, invite feedback.

## Embed
- Put the demo GIF near the top (after the hook) — same asset as the README.
- Link `docs/roadmap-cross-platform.md` for the "what's next" section.

## Cross-posting
- dev.to first (canonical), then mirror to Hashnode with canonical URL set.
- Lobsters: only if a member invites you; submit with the `authored` tag
  and participate — don't drive-by.
