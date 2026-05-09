# REFACTORING.md

Health roadmap for ccwork. Items grouped by the code-base pool they touch,
sorted within each pool from **structural** (architecture / correctness)
down to **cosmetic** (boilerplate / docs).

Status legend — used at the start of each item:

- **[S]** Structural — SRP/DRY/abstraction reshape. Largest blast radius.
- **[C]** Correctness — fixes a real or latent bug.
- **[E]** Efficiency — measurable runtime / memory win.
- **[P]** Process — tooling, CI, hygiene.
- **[X]** Cosmetic — test/dev-quality cleanup, no production effect.

The pools themselves are sorted by overall payoff: pools that gate other
work appear first.

---

## 1. Hook event routing & terminal lifecycle

Touches: `src/ui/main_window.py`, `src/core/hook_server.py`,
`src/core/terminal_session.py`, `bin/ccwork-hook-sink`.

This is the highest-leverage pool — `_working` desync is the source of
several existing bugs and it gates the per-session-routing work.

### 1.1 [C][S] Unify `_working` keying

**Files:** `src/ui/main_window.py:84`, `src/ui/repo_sidebar.py:194,
204, 308`

Three keying conventions live for the same conceptual question:

- `MainWindow._working` keyed by `repo.id`
- `RepoListModel._working` keyed by `normalize_path(path)`
- `RepoListModel._last_activity` keyed by raw `repo.path` (not
  normalized — can desync from the other two when a hook reports a
  non-canonical path)

CLAUDE.md flags this explicitly. The drift produces "spinner doesn't
flip" bugs whenever symlink/canonical path forms don't agree.

**Change:** Pick id-keyed everywhere. `RepoListModel._working` becomes
a derived view: a method `is_working(repo_id)` that consults a single
`set[str]` of working ids. Hook dispatch fans `cwd → list[id]` in one
helper (`_ids_for_cwd`). `_last_activity` keys on id too.

**Why:** Closes a class of subtle desync bugs and is a prerequisite
for clean per-session routing (1.2).

### 1.2 [S] Per-session hook routing

**Files:** `src/core/terminal_session.py`, `bin/ccwork-hook-sink`,
`src/ui/main_window.py:535-`

CLAUDE.md notes: "Hook events arrive with `cwd` and broadcast to
every matching id (per-session routing is future work)."

Today `_on_hook_event` broadcasts to every duplicate matching `cwd`;
the `siblings_working` workaround in `_on_terminal_finished` exists
to compensate.

**Change:** `terminal_session.build_session` sets `CCWORK_SESSION_ID`
to a uuid in the child env. `ccwork-hook-sink` emits it on the wire.
`_on_hook_event` routes to that specific id, falling back to broadcast
when the field is absent (back-compat).

**Why:** Eliminates the broadcast workaround; lets duplicate rows on
the same path show truly independent state.

### 1.3 [S] Extract terminal-lifecycle helper class

**Files:** `src/ui/main_window.py:311-336, 461-533`

`MainWindow` now owns: the terminal dict, the working-set, the
ensure/dispose/reload sequence, the stack widget swap, the title
update, the placeholder swap, and the failed/finished signal slots.
`_dispose_terminal` (added in the last pass) was a small step toward
splitting this.

**Change:** Extract `TerminalLifecycle(stack, sidebar, store)` that
owns `_terminals` and the ensure/dispose/reload methods. MainWindow
keeps the slot dispatch but delegates the heavy state.

**Why:** Halves MainWindow's responsibility surface; per-session
routing (1.2) lands in one place instead of three.

---

## 2. Sidebar UI subsystem

Touches: `src/ui/repo_sidebar.py` (currently ~1250 lines, single file).

### 2.1 [S] Extract `ArrangementAnimator`

**Files:** new `src/ui/arrangement_animator.py`; trim
`src/ui/repo_sidebar.py:777-1107`

`RepoSidebar` is currently a widget **and** a debouncer **and** an
animation controller **and** an idle detector. Five timers and seven
private fields exist solely for the reshuffle animation
(`_spinner_timer`, `_reorder_timer`, `_arrange_check_timer`,
`_arrange_step_timer`, `_last_sidebar_activity`, `_arrange_pending`,
`_arrange_steps_taken`, `_arrange_total_estimate`,
`_arrange_target_cache`).

**Change:** New `ArrangementAnimator(QObject)` taking
`(model, settings_provider)`. Owns the four animation timers and the
`_arrange_*` state. `RepoSidebar` exposes a single `request_arrange()`
and forwards `eventFilter` activity bumps via a method call.
`_count_bubble_swaps` and `_next_step_interval` move with it; both
are pure functions of `(current, target, steps_taken)` and become
trivially unit-testable without a `QApplication`.

**Why:** SRP. Animation logic gains its own test file. Sidebar
shrinks meaningfully.

### 2.2 [S] ~~Split `RepoListModel` from arrangement policy~~ — superseded

**Status:** dropped after landing 2.1.

After the animator extracted in 2.1, the remaining sort/group methods
on `RepoListModel` (`_activity_key`, `_grouping_key`,
`apply_auto_arrange`, `apply_terminal_grouping`, `target_order_ids`,
`_stable_sort`, `_reorder_by`) are ~60 lines using model-resident
state (`_last_activity`, `_active_ids`). Splitting into a separate
class would add indirection without reducing coupling — the policy
would still need to read model state, and every test touching the
sort methods would need re-pointing.

If the model grows further, revisit. For now, keep.

### 2.3 [E] Spinner repaint without per-row dispatch

**Files:** `src/ui/repo_sidebar.py:1107-1115`

`_advance_spinner` walks every row × 10 Hz, calling
`idx.data(ROLE_WORKING)` per row. With 50 repos that's 500 model
calls/sec just for the spinner.

**Change:** `RepoListModel` exposes `working_rows() -> list[int]` as
a precomputed list (cheap to maintain in `set_working`). The
spinner iterates the small list directly.

**Why:** Drops a constant background CPU cost.

### 2.4 [E] Selective branch refresh

**Files:** `src/ui/main_window.py:463`, `src/ui/repo_sidebar.py:266-277`

`_on_repo_selected → refresh_branches()` spawns N `git symbolic-ref`
subprocesses (2 s timeout each) on every click. Click latency
scales O(N).

**Change:** Add `RepoListModel.refresh_branch(path)`; the
selection slot calls only that. Keep a periodic full sweep wired to
`QApplication.focusWindowChanged` so stale branches still get caught.

**Why:** Click latency becomes O(1).

### 2.5 [E] Gate `scheduleDelayedItemsLayout` on grouping enabled

**Files:** `src/ui/repo_sidebar.py:914`

`set_terminal_active` always calls `scheduleDelayedItemsLayout()`
even when grouping is off, invalidating sizeHints uselessly.

**Change:** Wrap in `if self._delegate.group_enabled`.

**Why:** Trivial; eliminates one layout pass per terminal-active
toggle when grouping is off.

---

## 3. Repo store & path handling

Touches: `src/core/repo_store.py`.

### 3.1 [E] Cache `Repo.resolved`

**Files:** `src/core/repo_store.py:62-78, 152-174`

`index_of`/`indices_of`/`repos_for_path` call
`os.path.realpath(path)` plus `os.path.realpath(r.path)` for every
repo on every call. At 30+ repos with a steady stream of hook events
plus 10 Hz spinner repaints, this is tens of thousands of
`lstat`/`readlink` syscalls per second.

**Change:** Add a non-persisted `Repo.resolved: str` populated at
`add()` and `load()`. Lookups compare strings.

**Why:** Biggest single CPU win in the codebase. Compounds with
2.3 because `data()` and the spinner both walk this path.

---

## 4. Settings

Touches: `src/core/settings.py`.

### 4.1 [S] Settings schema migrations

**Files:** `src/core/settings.py`, `src/core/repo_store.py:31`

`SCHEMA_VERSION = 1` exists for `repos.json`, but `settings.json`
has no schema version. `Settings._raw` round-trips unknown keys, but
that only handles forward-compat (old reader, new writer); it doesn't
help when fields rename or split.

**Change:** Add `version: int` to `settings.json` and a small
`migrate(old_dict, from_version) -> dict` chain. Each version bump
gets one migration function. Same pattern in `repo_store.py`.

**Why:** Future field renames/splits become explicit instead of
silent default-application.

---

## 5. Tests

Touches: `tests/`.

### 5.1 [X] `tests/conftest.py` with shared fixtures

**Files:** `tests/test_preferences_dialog.py:23-25`,
`tests/test_repo_sidebar_autosort.py:30-38`,
`tests/test_repo_sidebar_terminal_active.py:23-25`,
`tests/test_repo_sidebar_grouping.py:24-32, 230-300`,
`tests/test_repo_sidebar_working.py:26-28`

`qapp` fixture is duplicated across 5 files; `_store_with` helper
across 2; the `RepoSidebar(store) + beginResetModel/endResetModel`
setup is open-coded 3× in `test_repo_sidebar_grouping.py` despite
an existing `_sidebar_with` helper.

**Change:** Add `tests/conftest.py` with session-scoped `qapp` plus
`make_store(paths, tmp_path)` and `make_sidebar(...)` factories.
Collapse the 3 inline setups in `test_repo_sidebar_grouping.py` to
call `_sidebar_with`.

**Why:** ~50 lines of boilerplate gone; future tests faster to write.

### 5.2 [X] Tests for `_count_bubble_swaps` and `_next_step_interval`

**Files:** new `tests/test_arrangement_animator.py` (post-2.1)

These are pure functions but currently only exercised through the
integration tests. Lands naturally with 2.1.

**Why:** Edge cases in the easing curve and inversion count get
direct coverage instead of inferred via the bubble walk.

---

## 6. Build, CI & dev tooling

Touches: repo root, `.github/`, `pyproject.toml`.

### 6.1 [P] CI for tests

**Files:** new `.github/workflows/test.yml`

Currently nothing fails the build if a test breaks. Run
`QT_QPA_PLATFORM=offscreen pytest -q` on push and PR.

**Why:** Catches regressions before they land.

### 6.2 [P] Pre-commit hooks (ruff)

**Files:** new `.pre-commit-config.yaml`, `pyproject.toml`

Add `ruff check --fix` + `ruff format`. One tool, no formatter wars.
Pin to a specific version in `pyproject.toml` so CI and local agree.

**Why:** Consistent style without manual policing; catches obvious
bugs (unused imports, undefined names) early.

### 6.3 [P] Type checking

**Files:** `pyproject.toml` (mypy config), `.github/workflows/test.yml`

Start with `mypy --strict` on `src/core/` (pure-Python, no Qt
stubs needed). Expand to `src/ui/` once PySide6 stubs settle.

**Why:** Catches the kind of "key-shape drift" that motivates 1.1
without needing a runtime test.

### 6.4 [P] Coverage gate

**Files:** `pyproject.toml`, CI workflow

`pytest-cov` is already a dependency. Capture the current coverage
%, fail CI if it drops; ratchet up over time.

**Why:** Coverage stays at least flat as the codebase grows.

### 6.5 [X] CHANGELOG.md

**Files:** new `CHANGELOG.md`

`docs/release-checklist.md` exists but there's no user-facing
changelog. Update per PR or per release.

**Why:** Users on `bin/ccwork-bashrc`-style installs can see what
changed across pulls.

---

## 7. Cross-platform

Touches: `src/main.py`, `src/ui/terminal_host.py`, `src/core/x11.py`.

### 7.1 [S] Replace XEmbed with a cross-platform terminal widget

**Status:** multi-PR project, not a single change. Realistic
effort is 1–4 weeks depending on widget choice. See
`docs/roadmap-cross-platform.md` for the full breakdown.

**Files (eventual):** `src/ui/terminal_host.py`, `src/core/x11.py`,
`src/core/xterm_osc.py`, `src/main.py` (Wayland-detection block).

**Why it's not a single PR:**
- Widget choice is a UX/legal decision (QTermWidget = mature but GPL,
  termqt = MIT/single-maintainer/unverified TUI fidelity for Claude's
  alt-screen UI, libvte via PyGObject = Linux-only, embed-an-emulator
  via pyte = full custom renderer).
- Once chosen, the dep adds either a compile-time toolchain
  (`shiboken6`/C++ stub) or a new pure-Python renderer.
- Wayland/macOS/Windows test environments are needed to verify each
  before merge.

**First step (landed):**
- `src/ui/terminal_host_protocol.py` defines `TerminalHostLike` — the
  surface `TerminalLifecycle` and `MainWindow` consume from a host
  (start, stop, is_running, focus_child, apply_live_settings,
  paste_text). The current `TerminalHost` satisfies it structurally;
  a future implementation can be slotted behind a factory.
- `TerminalLifecycle` already exists (item 1.3) so the lifecycle
  bookkeeping won't need to change when the host swaps.

**Second step (future PR):**
- Pick a widget. Soak-test against Claude Code's alt-screen UI in a
  branch.
- Inject the host class into `TerminalLifecycle` as a factory
  parameter; MainWindow chooses based on settings (`xterm` vs
  `termqt` vs …).

**Third step (future PR):**
- Wayland-native cleanup: drop the `QT_QPA_PLATFORM=xcb` force in
  `src/main.py`; delete `src/core/x11.py` once XEmbed is gone.

**Why bother:** unlocks Wayland-native, macOS, Windows. Largest item
on this list, but the only one that opens new platforms.

---

## Suggested ordering

If working through this end-to-end:

1. **6.1 + 6.2** — set up CI and pre-commit first so subsequent
   refactors are guarded.
2. **1.1** — unify `_working` keying. Closes existing bugs and
   un-tangles the state shape before bigger reshuffles.
3. **3.1** — cache `Repo.resolved`. Compounds with later UI items.
4. **2.1 + 2.2** — sidebar split. Big enough to be its own PR.
5. **1.2 + 1.3** — per-session routing + lifecycle extraction.
6. **2.3 + 2.4 + 2.5** — efficiency batch.
7. **5.1 + 5.2** — test hygiene catches up.
8. **4.1, 6.3, 6.4, 6.5** — process polish.
9. **7.1** — cross-platform, when there's appetite for it.

Each numbered item is sized to be one PR. Items in the same pool
that touch overlapping code (e.g. 2.1 and 2.2) are best landed
together; otherwise they're independent.
