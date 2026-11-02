# research/

Notes on other projects that solve problems near ccwork's, kept as reference for
features ccwork may adopt.

Each file names its source, the source version examined, and cites exact files in
that source so a claim can be checked.

## Contents

- [throng-borrowings.md](throng-borrowings.md) — ideas to adopt from throng
  (Bidthedog/throng), a Windows terminal/agent workspace with a detached PTY daemon.
- [ghosttyextreme-borrowings.md](ghosttyextreme-borrowings.md) — ideas to adopt
  from GhosttyEXTREME (steventsvik/GhosttyEXTREME), a macOS Ghostty fork for
  watching coding agents.
- [worktree-tool-practices.md](worktree-tool-practices.md) — how tools that run coding
  agents in git worktrees copy gitignored files, run setup scripts, place the
  worktree folder and mark a worktree session.
- [worktree-glyphs-and-shared-files.md](worktree-glyphs-and-shared-files.md) — which
  glyphs mark a git branch or worktree in text UIs, and how tools share large files
  between checkouts through links and protect them from writes.
- [claude-worktree-hook-probe/](claude-worktree-hook-probe/) — what `PWD`,
  `CLAUDE_PROJECT_DIR` and the payload `cwd` are in each hook event of a Claude
  worktree session.
