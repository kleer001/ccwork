# Live integration tests

End-to-end verification scripts that launch a real ccwork instance,
inject keys and text with xdotool (XTEST), and assert on log output,
the sandboxed config files and (where applicable) `wmctrl -l` window
appearance. **These need a
real X11 display** — they will not work under `QT_QPA_PLATFORM=offscreen`
and are excluded from the pytest sweep on purpose.

Scripts here are dev/QA aids, not part of the test suite proper. Run
individually from the repo root:

```bash
.venv/bin/python tests/live/check_focus_scoping.py
```

`harness.py` holds the shared parts:

| Part | What it does |
|---|---|
| `run_on_xvfb()` | Runs the script again on its own Xvfb display with openbox, a temporary `XDG_RUNTIME_DIR` (so the launched ccwork owns its own hook socket) and the D-Bus session address `disabled:` (so no notification reaches the desktop). No key or focus change reaches your desktop, and your running ccwork is not touched. |
| `evidence_dir()` | The run's evidence folder in the repo, `tmp/live-runs/<check>-<time>/`: the check's output (written line by line), the ccwork log and the screenshots. A new run removes the older runs of the check (`new_run_folder`). |
| `new_sandbox(name)`, `new_project(name, ignore)`, `claude_worktrees(repo)` | A new folder `tmp/wt-sandbox/<name>-<time>/` (the older ones are removed); that folder and the git repo `proj` in it, with one commit (a README, and a `.gitignore` with `ignore`); and the folder where Claude Code makes the repo's worktrees. Each run gets a new path because Claude Code keeps the folder trust of a path. |
| `git(*args, date, check)`, `seed(path, files, message)` | From `tests/gitrepo.py`, which the unit tests use too: git with a fixed author and committer (its stdout, stripped), and a new repo on `main` with one commit of `files`. |
| `wait_until(predicate, seconds, step)` | Calls `predicate` every `step` seconds until it holds (True), or until `seconds` pass (False). |
| `CLAUDE`, `loads_ccwork_claude_md(folder)` | The `claude` command to type in a sandbox: its `--settings` give `claudeMdExcludes`, which keeps ccwork's CLAUDE.md (in a folder above each sandbox) out of the session. And whether a `CLAUDE` session in `folder` loads that file, from the memory files that `/context` lists. |
| `with ccwork(sandbox, rows, settings) as app:` | Writes `rows` (paths or row dicts) to `<sandbox>/config/ccwork/repos.json` and `settings` (TOML text) to its `settings.toml`, starts ccwork with that `XDG_CONFIG_HOME`, waits for its window (matched by `WM_CLASS=main.py.ccwork`, not by a title: a shell prompt in a title often holds "ccwork") and focuses it. At the end it stops ccwork and removes the worktrees that Claude Code made in each row's repo. |
| `app` (a `Ccwork`) | `proc`, `config` (its ccwork config folder), `log()`, `store()` (`repos.json`), `row()`, `row_path()`, `recent()`, `hook_events()`, `dispatches()`, `focus()`, `click(x, y, button)`, `open_terminal()` (Ctrl+Shift+1). |
| `key(*keys, pause)`, `type_text(text)`, `type_line(text)` | xdotool key names, text, and text then Enter. |
| `windows()`, `screenshot(name)`, `with other_window(title):` | The `wmctrl -l` list, a PNG of the display in the evidence folder, and a plain xterm to focus away from ccwork. |
| `watch_claude(app, worktree, tick)` | Samples the first row's path until `ClaudeExited`. |
| `check_follow(name, command)` | The whole check that a row follows a `claude` command into `.claude/worktrees/<name>` and back, and that a `CLAUDE` session in the repo does not load ccwork's CLAUDE.md. |
| `report(checks)` | Prints each check and `result: PASS` or `FAIL`, and gives the exit code. |

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
| `check_terminal_input.py` | Launches no ccwork: it embeds one `TerminalHost` in a plain window. A typed command (`type_text`) and a pasted command (`paste_clipboard`) each run in a real embedded xterm, and `send_suspend` stops a foreground `sleep`. Guards the XTEST input path, since PTY-slave writes never reach the shell. |
| `check_worktree_follow.py` | Runs one real `claude -w <name> -p` prompt in a ccwork terminal on the harness display. Passes when the row follows Claude into `.claude/worktrees/<name>` and returns to the repo on `ClaudeExited`, with no `home` and an empty `recent`, and when a sandbox session does not load ccwork's CLAUDE.md. Needs `install.sh` hooks and a Claude login. |
| `check_enter_worktree.py` | Runs one real `claude -p` prompt that calls the EnterWorktree tool (allowed with `--allowedTools`). Passes when the row moves to `.claude/worktrees/<name>` during the turn and returns to the repo on `ClaudeExited`, with no `home` and an empty `recent`, and when a sandbox session does not load ccwork's CLAUDE.md. Needs `install.sh` hooks and a Claude login. |
| `check_subagent_worktree.py` | Runs one real `claude -p` prompt that starts a subagent with `isolation: worktree`. Samples `git worktree list` during the run. Passes when SubagentStart and SubagentStop arrive, a second worktree exists during the run, and the row never leaves the repo. Needs `install.sh` hooks and a Claude login. |
| `check_worktree_interactive.py` | Types into interactive Claude Code sessions. It accepts the folder trust prompt once, runs `claude -w` and exits with "Remove worktree" (the script writes a file first, so that Claude asks), then sends two Haiku prompts in one session: EnterWorktree, then ExitWorktree with action remove. Passes when the row is on each worktree while Claude is in it, back on the repo after each exit (after ExitWorktree, on the same turn's Stop), with both folders and branches gone, no `home` and an empty `recent`. Claude Code records the trust of each sandbox repo in `~/.claude.json`; for `claude -w`, the trust of the ccwork folder above it does not count. Needs `install.sh` hooks and a Claude login. |
| `check_worktree_crash.py` | Runs one real `claude -p` prompt that calls EnterWorktree and then sleeps, and kills ccwork while the row is on the worktree. Passes when `open_sessions.json` records the folder where the session started (the first `cwd` of its transcript), where `claude --resume <id>` finds it. Needs `install.sh` hooks and a Claude login. |
| `check_make_worktree.py` | With the worktree folder setting at `<sandbox>/worktrees`, right-clicks a row, picks *Make worktree…* with the keyboard and types `fix/a`. Passes when the second row is on `<sandbox>/worktrees/proj-fix-a` with the source badge and a blank title, the folder is on `fix/a` with `ccworkBase = main`, the new terminal (typed into with no click: it takes the focus when it maps) prints that folder and branch, and of the ignored `.env`, 2 MiB `model.bin` and `tmp/` only `.env` is copied. The source `.venv` (made by `uv venv`) is rebuilt in the worktree with the same Python version. The result screenshot shows the copy report and the setup commands. |
| `check_remove_worktree.py` | Removes two worktree rows with the delete box on. Passes when git refuses the dirty one (a message window, folder and row stay) and the clean one's folder, branch and row go, with `recent` empty. |
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
