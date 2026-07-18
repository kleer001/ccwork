# Good-first-issue backlog (draft)

Candidate issues scoped for a newcomer who doesn't know the codebase.
**The backlog is the work; the label is trivial.** File the ones you like
as real GitHub issues with the `good first issue` or `help wanted` label —
that's what converts browsers into first PRs and lists ccwork in GFI
aggregators. Each entry names likely files so a stranger can start.

> These are *candidates* drafted from `TODO.md`, `CLAUDE.md`, and the code.
> Review before filing; delete any that are stale or too large.

---

### 1. Add more example colors to the badges.toml schema docs
**Label:** good first issue · docs
The `badges.toml` override supports `#hex`, `rgb()`, `hsv()`, and SVG color
names (`src/ui/badge_theme.py`). Expand the module docstring's example
schema with one worked example per color format so users can copy-paste.
**Files:** `src/ui/badge_theme.py`. **Scope:** docs only, no logic.

### 2. Friendlier error when `xterm` is not installed
**Label:** good first issue
If `xterm` isn't on `PATH`, the terminal host fails opaquely. Detect a
missing `xterm` at spawn time and surface a clear message (status bar or
dialog) pointing the user at their package manager.
**Files:** `src/ui/terminal_host.py`, `src/core/terminal_session.py`.
**Scope:** small, testable with a mocked `PATH`.

### 3. `--version` flag for `bin/ccwork` / `src.main`
**Label:** good first issue
Print `__version__` (`src/__init__.py`) and exit when `--version` is
passed, before Qt initializes.
**Files:** `src/main.py`, maybe `bin/ccwork`. **Scope:** tiny, unit-testable.

### 4. Document every `tests/live/` script's purpose in its README
**Label:** good first issue · docs
`tests/live/README.md` should have a one-line purpose for each script
(several exist: `check_focus_scoping.py`, `check_keys_dispatch.py`,
`check_f1_cheatsheet.py`, `check_window_geometry.py`,
`audition_subagent_glyphs.py`, `preview_subagent_sequences.py`,
`probe_xgrabkey.py`). Fill any gaps.
**Files:** `tests/live/README.md`. **Scope:** docs only.

### 5. Surface the Wayland→XWayland fallback to the user
**Label:** good first issue
`src/main.py` forces `QT_QPA_PLATFORM=xcb` under Wayland. Log a one-line
INFO message (and optionally a first-run hint) so Wayland users understand
why ccwork is running under XWayland.
**Files:** `src/main.py`. **Scope:** small, log-level assertion testable.

### 6. Add a `CCWORK_TERMINAL` env knob stub (docs + plumbing)
**Label:** help wanted
`TODO.md` calls for a `CCWORK_TERMINAL=termqt` spike. As a first step,
thread a single env-var read through `terminal_session.py` that only
accepts `xterm` today and logs "unsupported terminal, falling back to
xterm" otherwise — the seam for the future widget swap.
**Files:** `src/core/terminal_session.py`. **Scope:** medium; sets up
future work without implementing the alternate widget.

### 7. Respect `NO_COLOR` / a mono theme for the dashboard accents
**Label:** help wanted
Dashboard accents come from `badge_theme`. Add an opt-out (env var or
setting) that renders the splash dashboard in a neutral monochrome palette
for low-color or accessibility preferences.
**Files:** `src/ui/empty_state.py`, `src/ui/badge_theme.py`. **Scope:**
medium; good radar/chart-painting starter.

### 8. Unit-test the Roman-numeral instance suffix edge cases
**Label:** good first issue · tests
`repo_store.py` computes `(I)`, `(II)`… suffixes for duplicate paths and
resets to bare when the count drops to 1. Add tests for the reset and
re-sequence behavior around 1↔2↔3 duplicates.
**Files:** `tests/test_repo_store.py`. **Scope:** tests only.

### 9. Quickstart GIF alt-text + reduced-motion note in README
**Label:** good first issue · docs
Once a demo GIF lands, ensure it has descriptive alt text and add a
one-line "prefers-reduced-motion" note linking to a static screenshot.
**Files:** `README.md`, `docs/images/`. **Scope:** docs/accessibility.

### 10. Add a `make test` / `just test` convenience wrapper
**Label:** good first issue
Wrap the offscreen pytest incantation in a `Makefile` or `justfile` target
so contributors don't have to remember `QT_QPA_PLATFORM=offscreen …`.
Reference it from `CONTRIBUTING.md`.
**Files:** new `Makefile`/`justfile`, `CONTRIBUTING.md`. **Scope:** small.
