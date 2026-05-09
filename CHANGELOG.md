# Changelog

All notable user-visible changes go here. Format follows [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/); the project loosely
follows [SemVer](https://semver.org).

Entries land per PR, not per release. The bottom of the file is the
oldest entry; the top of `[Unreleased]` is the newest change.

## [Unreleased]

### Added
- `bin/ccwork-hook-sink` now emits a `repo_id` field — when present, the
  GUI routes hook events to that specific instance instead of
  broadcasting across every duplicate row sharing the cwd. Falls back
  to broadcast on legacy hooks (REFACTORING.md 1.2).
- Schema-migration seam in `settings.json` and `repos.json`. Loaders
  read the on-disk `version` and apply registered migrations up to
  `SCHEMA_VERSION`. No migrations registered yet — the seam exists for
  future field renames/splits (REFACTORING.md 4.1).
- Pre-commit hooks (`ruff` lint + format) and CI workflow extensions
  (`ruff check`, `mypy`, Python 3.10/3.11/3.12 matrix, coverage gate).
- `CHANGELOG.md` — this file.

### Changed
- Sidebar reshuffle animation extracted from `RepoSidebar` into a
  dedicated `ArrangementAnimator`. Pure helpers (inversion count, sine
  cadence) get their own test file (REFACTORING.md 2.1).
- Terminal lifecycle (spawn/dispose/reload) extracted from
  `MainWindow` into `TerminalLifecycle`. The dict + signal-wiring +
  shutdown sequence live in one place (REFACTORING.md 1.3).
- `_working` and `_last_activity` are id-keyed across the codebase;
  hook events fan path → ids in one helper. Closes a class of
  symlink-vs-canonical-path desync bugs (REFACTORING.md 1.1).
- `Repo.resolved` is cached at construction so `RepoStore` lookups
  compare strings instead of stat'ing every repo per call. Drops
  per-paint and per-hook overhead at 30+ repos (REFACTORING.md 3.1).
- Spinner repaint iterates a small `working_rows()` list instead of
  every row × 10 Hz (REFACTORING.md 2.3).
- Selection click refreshes the clicked repo's branch only; a periodic
  full sweep on window focus keeps the rest fresh. Click latency is
  O(1) regardless of repo count (REFACTORING.md 2.4).

### Fixed
- `RepoListModel.remove_repo_at` now also discards the removed id from
  `_active_ids` — previously dead ids persisted forever when a repo
  was removed without first closing its terminal.

### Internal
- `tests/conftest.py` owns the session-scoped `qapp` fixture and
  `make_store(...)` factory. Drops ~50 lines of boilerplate across
  8 test modules.
- `_step_arrange` caches the bubble-walk total swap count at walk
  start and decrements per step, instead of re-simulating O(N²) per
  tick. Recomputed only when the target shifts mid-walk.

## Earlier

This file starts here. Prior history is in `git log`.
