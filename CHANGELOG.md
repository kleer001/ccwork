# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Community-health files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`, this changelog, and GitHub issue / pull-request templates.
- `docs/marketing/` — growth strategy and drafted (unpublished) launch
  assets.

### Changed
- Repository layout tidied: assets live under `assets/`, design mockups
  under `docs/design/`, and long-form docs under `docs/history/` and
  `docs/blog/`.

## [0.2.0] - 2026

### Added
- Weekly-retro **splash dashboard**: narrative summary, 8-week commit
  trend, per-repo radar "fingerprint" cards, and an idle-repo strip, all
  computed locally from `git` (`src/core/repo_stats.py`).
- **Recent recall** slot and a **Dashboard** slot at the bottom of the repo
  stack.
- **Crash-recovery banner** offering `claude --resume` for sessions left
  open by an unclean shutdown (`src/core/session_recovery.py`).
- Configurable badge theme via `~/.config/ccwork/badges.toml`
  (`src/ui/badge_theme.py`).
- Subagent twinkle indicator and richer per-session state tracking.

### Fixed
- Hook server refuses to steal a live instance's socket.
- Working spinner is preserved when a sibling session on the same path
  exits; spinner/twinkle clear correctly when a terminal exits.

## [0.1.0] - 2026

### Added
- Initial PyQt/PySide6 desktop app: sidebar of repos, embedded `xterm`
  terminals via XEmbed, and a live alerts panel driven by Claude Code
  Stop/Notification hooks.
- `install.sh` / `bootstrap.sh` installer with `--dry-run` and
  `--uninstall`.

[Unreleased]: https://github.com/kleer001/ccwork/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/kleer001/ccwork/releases/tag/v0.2.0
[0.1.0]: https://github.com/kleer001/ccwork/releases/tag/v0.1.0
