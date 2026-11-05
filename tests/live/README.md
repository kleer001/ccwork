# Live integration tests

End-to-end scripts that run a real ccwork on their own Xvfb display, drive
it with xdotool and assert on its log, its sandboxed config files and its
windows. They need `Xvfb`, `openbox`, `xdotool`, `wmctrl` and ImageMagick
`import`, and are excluded from the pytest sweep on purpose. Run each one
from the repo root:

```bash
.venv/bin/python tests/live/check_focus_scoping.py
```

`harness.py` holds the shared parts; the docstring of each part says what it
does. The docstring of each check says what it does and when it passes. The
checks marked *Claude* run real Claude Code prompts, so they need the
`install.sh` hooks and a Claude login.

## Why they live outside the pytest tree

These scripts have a `main()` and no `test_*` functions, so they'd be
collected by pytest as "no tests" warnings and add noise. They also
take 3–10 seconds each, need an X server, and exercise real Qt event
loops + xterm spawns — wrong shape for the offscreen-fast pytest
sweep. Renamed off the `*_test.py` glob so pytest's default discovery
skips them entirely.

## Index

| Script | Purpose |
|---|---|
| `check_focus_scoping.py` | **Load-bearing.** The key grab fires while ccwork has the focus, and not while another window has it. Catches the regression where shortcuts become global again. |
| `check_keys_dispatch.py` | Each shipped shortcut dispatches. |
| `check_f1_cheatsheet.py` | F1 opens the keyboard-shortcuts dialog. |
| `check_window_geometry.py` | A clean Ctrl+Shift+Q quit saves the window geometry. |
| `check_terminal_input.py` | Typed text, pasted text and Ctrl+Z reach the shell in one embedded xterm, with no ccwork. |
| `check_worktree_follow.py` | *Claude.* A row follows `claude -w` into its worktree and comes back. |
| `check_enter_worktree.py` | *Claude.* A row follows the EnterWorktree tool and comes back. |
| `check_subagent_worktree.py` | *Claude.* A subagent in its own worktree does not move the row. |
| `check_worktree_interactive.py` | *Claude.* Interactive sessions move a row into a worktree and back: `claude -w` with its exit dialog, then EnterWorktree and ExitWorktree. |
| `check_worktree_crash.py` | *Claude.* After a crash in an EnterWorktree session, crash recovery records the folder that `claude --resume` needs. |
| `check_make_worktree.py` | *Make worktree…* makes a row on a new worktree, copies the small ignored files and sets up the venv. |
| `check_remove_worktree.py` | The delete box removes a clean worktree with its branch, and git refuses a dirty one. |
| `probe_xgrabkey.py` | Diagnostic — a minimal standalone X grabber (no Qt). Useful when investigating whether XTest injection or XGrabKey itself is the failure mode. Run, then in another shell trigger the combo or inject manually. |
| `audition_subagent_glyphs.py` | Visual tool (not inject-and-assert). Steps through candidate subagent-twinkle glyphs one at a time — painted exactly as `RepoDelegate` renders them, beside an animating spinner with centre crosshairs — and lets you keep/drop each. Prints the kept frame list to stdout. |
| `preview_subagent_sequences.py` | Visual tool. Animates two orderings of the chosen subagent glyphs side by side at the real twinkle rate, so you can compare candidate `subagent_frames` sequences before committing one. |

## Adding a new live test

Follow the existing pattern:

1. Call `harness.run_on_xvfb()` first in the `__main__` block.
2. Make the sandbox and its repos (`harness.new_project`, or `harness.new_sandbox`
   and `harness.seed`).
3. Do the check inside `with harness.ccwork(sandbox, rows) as app:`.
4. Inject with `harness.key` and `harness.type_line`. Call `app.focus()`
   after a dialog closes, if the next key must reach ccwork's grab. Type
   `harness.CLAUDE`, not `claude`, to start a Claude Code session.
5. Read `app.log()`, `app.store()` or `harness.windows()` to verify the
   side effect.
6. Return `harness.report(checks)` as the exit code.
