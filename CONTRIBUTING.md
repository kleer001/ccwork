# Contributing to ccwork

Thanks for your interest in ccwork! Contributions of every kind are
welcome — bug reports, feature ideas, docs, and code. This project is
solo-maintained today, so a clear PR or a well-scoped issue goes a long
way.

> **Claude-Code-friendly repo.** ccwork ships a detailed
> [`CLAUDE.md`](CLAUDE.md) describing the whole architecture. If you use
> Claude Code, point it at the repo root and it will pick up the
> conventions automatically.

## Platform requirement

ccwork is **Linux + X11 or XWayland only**. It embeds real `xterm`
processes via XEmbed (`xterm -into <winId>`), which has no Wayland
equivalent. On a Wayland session `src/main.py` forces `QT_QPA_PLATFORM=xcb`
so both Qt and xterm run as X11 clients. macOS/Windows are not supported
(see [`docs/roadmap-cross-platform.md`](docs/roadmap-cross-platform.md)).

## Dev setup

```bash
git clone https://github.com/kleer001/ccwork
cd ccwork
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# Launch the GUI (needs a real X display + xterm installed)
./bin/ccwork
# or
.venv/bin/python -m src.main
```

`requirements.txt` pins the runtime + test deps (`PySide6>=6.6`,
`tomlkit`, `pytest`, `pytest-cov`). You also need `xterm` on your `PATH`.

## Running the tests

Qt needs a platform plugin; `offscreen` is fine and is what CI uses.

```bash
# Full suite
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q

# A single file or test
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings.py -q
```

The `tests/live/` scripts are **not** pytest tests — they launch a real
ccwork and inject X keystrokes, and must be run individually on an X11
display. `tests/live/check_focus_scoping.py` is the load-bearing guard
against the "shortcuts leak globally" regression; run it if you touch the
keybinding / XGrabKey path. See `tests/live/README.md`.

## Conventions worth knowing

The [`CLAUDE.md`](CLAUDE.md) "Conventions worth knowing" section is the
authoritative guide. The high points:

- **Don't catch hook-input errors at the call site** — `HookServer`
  already swallows malformed lines.
- **xterm spawn args are centralized** in `XtermSettings.to_xterm_args()`
  — extend the settings dataclass, don't append flags ad hoc.
- **Badge glyphs / colors / labels live in `src/ui/badge_theme.py`** — the
  single theming source; overridable via `~/.config/ccwork/badges.toml`.
- **User-state and Claude-alert state are storage-separate.** A Claude
  event must never mutate `_last_focused`; a user navigation must never
  mutate `_status`/`_working`.
- **`apply_hook_event` is the single entry point** for hook-driven state
  changes — extend the event → mutation table, don't sequence mutators
  from new call sites.
- There is no separate lint/format step; match the surrounding style.

## Submitting a change

1. Fork and branch from `main`.
2. Keep the change focused; one logical change per PR.
3. Add or update tests for behavior changes (`tests/` uses the shared
   `qapp` fixture and `StubHookServer` from `tests/conftest.py`).
4. Run the full suite (`QT_QPA_PLATFORM=offscreen … pytest -q`) and make
   sure it's green.
5. Update docs / `CLAUDE.md` if you changed architecture, and add a
   `CHANGELOG.md` entry under "Unreleased".
6. Open the PR using the template; describe what changed and how you
   verified it.

## Good first issues

Looking for a place to start? Check the
[`good first issue`](https://github.com/kleer001/ccwork/labels/good%20first%20issue)
and [`help wanted`](https://github.com/kleer001/ccwork/labels/help%20wanted)
labels. If none are open, file an issue describing what you'd like to work
on and we'll scope it together.

## Reporting bugs & asking questions

- **Bugs:** open an issue with the bug-report template. Include your
  distro, whether you're on X11 or XWayland, and your `xterm` version —
  those three details resolve most reports.
- **Security:** see [`SECURITY.md`](SECURITY.md) — please don't file
  public issues for vulnerabilities.

By contributing you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md).
