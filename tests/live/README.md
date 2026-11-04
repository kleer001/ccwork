# Live integration tests

End-to-end verification scripts that launch a real ccwork instance,
inject synthetic keypresses via `libXtst`, and assert on log output
and (where applicable) `wmctrl -l` window appearance. **These need a
real X11 display** — they will not work under `QT_QPA_PLATFORM=offscreen`
and are excluded from the pytest sweep on purpose.

Scripts here are dev/QA aids, not part of the test suite proper. Run
individually from the repo root:

```bash
.venv/bin/python tests/live/check_focus_scoping.py
```

`harness.py` holds the shared parts. `harness.run_on_xvfb()` runs the
script again on its own Xvfb display with openbox, a temporary
`XDG_RUNTIME_DIR` (so the launched ccwork owns its own hook socket) and
the D-Bus session address `disabled:` (so no notification reaches the
desktop). No key or focus change reaches your desktop, and your running
ccwork is not touched. Each run keeps its evidence in the repo, in
`tmp/live-runs/<check>-<time>/` (`harness.evidence_dir()`): the check's
output, the ccwork log and the screenshots. `harness.screenshot(path)`
saves the display as a PNG (ImageMagick `import`);
`harness.open_other_window(title)` starts a plain xterm to focus away from
ccwork; `harness.ccwork_window()` waits for the ccwork window and gives its id, and
`harness.focus_ccwork()` focuses it;
`harness.git(*args)` runs git and returns its output; `harness.seed_repo(path)`
makes a repo with one commit.
`check_terminal_input.py` keeps its own Xvfb code: it launches no ccwork
and needs no window manager.

Each script:

- Spawns ccwork as a subprocess in a sandbox `XDG_CONFIG_HOME` so the
  user's real `~/.config/ccwork/settings.toml` and `repos.json` are
  untouched.
- Forces focus to ccwork (or away from it, depending on the check) via
  `wmctrl -ia <window-id>` — matched by `WM_CLASS=main.py.ccwork`
  rather than title substring (a shell prompt in a title often contains
  "ccwork" as the cwd, which would mis-match a title search).
- Cleans up the spawned ccwork process on exit. Stray xterm children
  from inside ccwork stop with it.

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
| `check_focus_scoping.py` | **Load-bearing.** Verifies that the MainWindow-scoped XGrabKey does NOT activate when another window has focus, and DOES activate when ccwork's window is focused. Catches the regression where shortcuts become global again. |
| `check_keys_dispatch.py` | Smoke-checks every shipped shortcut combo (Ctrl+Shift+P/O, Ctrl+Tab/Shift+Tab, Ctrl+Shift+1) — each should produce a `KeyGrabFilter DISPATCH` log line and (where applicable) a visible dialog window. |
| `check_f1_cheatsheet.py` | F1 opens the keyboard-shortcuts dialog. Visible-window check via wmctrl matching `"Keyboard shortcuts"`. |
| `check_window_geometry.py` | A clean Ctrl+Shift+Q quit writes a non-empty base64 `geometry` blob into the sandboxed `settings.toml`. |
| `check_terminal_input.py` | Runs on its own Xvfb display. A typed command (`type_text`) and a pasted command (`paste_clipboard`) each run in a real embedded xterm, and `send_suspend` stops a foreground `sleep`. Guards the XTEST input path, since PTY-slave writes never reach the shell. |
| `check_worktree_follow.py` | Runs one real `claude -w <name> -p` prompt in a ccwork terminal on the harness display. Passes when the row follows Claude into `.claude/worktrees/<name>` and returns to the repo on `ClaudeExited`, with no `home` and an empty `recent`. Needs `install.sh` hooks and a Claude login. |
| `check_enter_worktree.py` | Runs one real `claude -p` prompt that calls the EnterWorktree tool (allowed with `--allowedTools`). Passes when the row moves to `.claude/worktrees/<name>` during the turn and returns to the repo on `ClaudeExited`, with no `home` and an empty `recent`. Needs `install.sh` hooks and a Claude login. |
| `check_subagent_worktree.py` | Runs one real `claude -p` prompt that starts a subagent with `isolation: worktree`. Samples `git worktree list` during the run. Passes when SubagentStart and SubagentStop arrive, a second worktree exists during the run, and the row never leaves the repo. Needs `install.sh` hooks and a Claude login. |
| `check_worktree_interactive.py` | Types into interactive Claude Code sessions. It accepts the folder trust prompt once, runs `claude -w` and exits with "Remove worktree" (the script writes a file first, so that Claude asks), then sends two Haiku prompts in one session: EnterWorktree, then ExitWorktree with action remove. Passes when the row is on each worktree while Claude is in it, back on the repo after each exit (after ExitWorktree, on the same turn's Stop), with both folders and branches gone, no `home` and an empty `recent`. Claude Code records the trust of the temporary folder in `~/.claude.json`. Needs `install.sh` hooks and a Claude login. |
| `check_worktree_crash.py` | Runs one real `claude -p` prompt that calls EnterWorktree and then sleeps, and kills ccwork while the row is on the worktree. Passes when `open_sessions.json` records the folder where the session started (the first `cwd` of its transcript), where `claude --resume <id>` finds it. Needs `install.sh` hooks and a Claude login. |
| `check_make_worktree.py` | Right-clicks a row, picks *Make worktree…* with the keyboard and types `fix/a`. Passes when the second row is on `<parent>/proj-fix-a` with the source badge and a blank title, the folder is on `fix/a` with `ccworkBase = main`, the new terminal prints that folder and branch, and of the ignored `.env`, 2 MiB `model.bin` and `tmp/` only `.env` is copied. The source `.venv` (made by `uv venv`) is rebuilt in the worktree with the same Python version. The result screenshot shows the copy report and the setup commands. |
| `check_remove_worktree.py` | Removes two worktree rows with the delete box on. Passes when git refuses the dirty one (a message window, folder and row stay) and the clean one's folder, branch and row go, with `recent` empty. |
| `probe_xgrabkey.py` | Diagnostic — a minimal standalone X grabber (no Qt). Useful when investigating whether XTest injection or XGrabKey itself is the failure mode. Run, then in another shell trigger the combo or inject manually. |
| `audition_subagent_glyphs.py` | Visual tool (not inject-and-assert). Steps through candidate subagent-twinkle glyphs one at a time — painted exactly as `RepoDelegate` renders them, beside an animating spinner with centre crosshairs — and lets you keep/drop each. Prints the kept frame list to stdout. |
| `preview_subagent_sequences.py` | Visual tool. Animates two orderings of the chosen subagent glyphs side by side at the real twinkle rate, so you can compare candidate `subagent_frames` sequences before committing one. |

## Adding a new live test

Follow the existing pattern:

1. Call `harness.run_on_xvfb()` first in the `__main__` block.
2. Open an `XDG_CONFIG_HOME=<tmp>` subprocess running `python -m src.main`,
   with its log at `harness.evidence_dir() / "ccwork.log"`.
3. Wait for the `global keys:` startup line in the log.
4. `harness.focus_ccwork()` before injecting if you need the grab to
   activate.
5. Inject via `XTestFakeKeyEvent` (see existing scripts for the
   ctypes wiring).
6. Read the log and/or `wmctrl -l` to verify the side effect.
7. Kill the subprocess in a `finally` block.
8. Print `result: PASS` / `result: FAIL` and exit 0/non-zero.
