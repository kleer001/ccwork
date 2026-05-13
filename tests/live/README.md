# Live integration tests

End-to-end verification scripts that launch a real ccwork instance,
inject synthetic keypresses via `libXtst`, and assert on log output
and (where applicable) `wmctrl -l` window appearance. **These need a
real X11 display** — they will not work under `QT_QPA_PLATFORM=offscreen`
and are excluded from the pytest sweep on purpose.

Scripts here are dev/QA aids, not part of the test suite proper. Run
individually from a working X session:

```bash
.venv/bin/python tests/live/check_focus_scoping.py
```

Each script:

- Spawns ccwork as a subprocess in a sandbox `XDG_CONFIG_HOME` so the
  user's real `~/.config/ccwork/settings.toml` and `repos.json` are
  untouched.
- Forces focus to ccwork (or away from it, depending on the check) via
  `wmctrl -ia <window-id>` — matched by `WM_CLASS=main.py.ccwork`
  rather than title substring (Konsole's prompt often contains
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
| `probe_xgrabkey.py` | Diagnostic — a minimal standalone X grabber (no Qt). Useful when investigating whether XTest injection or XGrabKey itself is the failure mode. Run, then in another shell trigger the combo or inject manually. |

## Adding a new live test

Follow the existing pattern:

1. Open an `XDG_CONFIG_HOME=<tmp>` subprocess running `python -m src.main`.
2. Wait for the `global keys:` startup line in the log.
3. `_focus_ccwork()` (see `check_focus_scoping.py`) before injecting if
   you need the grab to activate.
4. Inject via `XTestFakeKeyEvent` (see existing scripts for the
   ctypes wiring).
5. Read the log and/or `wmctrl -l` to verify the side effect.
6. Kill the subprocess in a `finally` block.
7. Print `result: PASS` / `result: FAIL` and exit 0/non-zero.
