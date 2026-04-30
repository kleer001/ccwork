# Contributing to ccwork

Thanks for your interest. ccwork is a small, focused project — the goal is a
solid Qt GUI for running Claude Code across many repos. Bug reports, fixes,
and small enhancements are all welcome.

## Platform

ccwork is **Linux + X11 (or XWayland) only**. The GUI embeds real `xterm`
processes via XEmbed, which has no Wayland-native equivalent. If you're on
Wayland, ccwork forces `QT_QPA_PLATFORM=xcb` and runs under XWayland — that
path works, but Wayland-native is out of scope.

macOS and Windows are not supported and not on the roadmap.

## Dev setup

```bash
git clone https://github.com/kleer001/ccwork ~/ccwork
cd ~/ccwork
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Run the GUI directly (no install needed for development):

```bash
./bin/ccwork
# or
.venv/bin/python -m src.main
```

Increase log verbosity with `CCWORK_LOG=DEBUG ./bin/ccwork`.

## Tests

```bash
# Full suite (Qt needs a platform — offscreen is fine):
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q

# Single file or test:
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings.py -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings.py::test_ui_settings_min_width_enforced_on_load -q
```

Please add or update tests for any behavior change. There's no separate lint
or format step.

## Architecture notes

`CLAUDE.md` in the repo root has the architectural overview — three
subsystems (UI / core / external integration), event flow from Claude Code
hooks to the sidebar, and a few invariants worth knowing before you touch
specific areas (Settings `_raw` round-trip, xterm spawn args centralized in
`XtermSettings.to_xterm_args()`, sidebar splitter-only width). Worth a skim
before a non-trivial PR.

## Filing a bug

Use the bug-report template. Include:

- Distro and version (`cat /etc/os-release`)
- Whether you're on X11 or Wayland (`echo $XDG_SESSION_TYPE`)
- Python version (`python3 --version`)
- xterm version (`xterm -version`)
- Steps to reproduce
- Debug log: `CCWORK_LOG=DEBUG ./bin/ccwork` and paste the relevant output

## Pull requests

- Keep changes scoped — one logical change per PR.
- Match the existing code style (no separate linter is configured; just look
  at neighboring files).
- Run the test suite locally before pushing.
- If you're touching the install scripts, please test `--dry-run` and
  `--uninstall` on a clean shell.

That's it. Thanks for contributing.
