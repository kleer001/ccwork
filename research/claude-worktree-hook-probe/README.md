# Probe: what a hook sees in a Claude worktree session

Claude Code 2.1.314, `claude -p`, model haiku, in a fresh git repository with
one empty commit. `settings.json` adds `dump.sh` to SessionStart,
UserPromptSubmit, Stop and SessionEnd. `dump.sh` records the hook process
`PWD`, `CLAUDE_PROJECT_DIR`, and the payload `cwd`. The ccwork variables
(`CCWORK_GUI`, `CCWORK_ROW_ID`, `CCWORK_CLAUDE_DEPTH`) were unset, so the ccwork
hook sink sent nothing. `<scratch>` in the logs stands for the temporary
folder that held the repository.

| Run | Command | Log |
|---|---|---|
| 1 | `claude -p --worktree probe "Reply with the single word OK."` | `run1-worktree-flag.txt` |
| 2 | `claude -p "Call the EnterWorktree tool … named probe2 …" --allowedTools=EnterWorktree` | `run2-enter-worktree.txt` |

## Results

Run 1 (`--worktree` at start): all four events saw `PWD`, `CLAUDE_PROJECT_DIR`
and payload `cwd` = `<repo>/.claude/worktrees/probe`.

Run 2 (`EnterWorktree` during the session): SessionStart and UserPromptSubmit
saw `<repo>` for all three values. Stop and SessionEnd saw `PWD` and payload
`cwd` = `<repo>/.claude/worktrees/probe2`, and `CLAUDE_PROJECT_DIR` = `<repo>`.

`bin/ccwork-hook-sink` sends `cwd` as `${CLAUDE_PROJECT_DIR:-$PWD}`. So in run 1
ccwork gets the worktree as `cwd`, and its SessionStart rebind moves the row into
the worktree. In run 2 ccwork gets `<repo>`, and the row does not move.

Not covered: interactive sessions, subagents with `isolation: worktree`, and the
exit prompt that removes a worktree.
