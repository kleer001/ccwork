# Release checklist

A short, repeatable script for cutting a ccwork release. Designed to be done
by a human in one sitting; nothing here is automated.

## Pre-flight

- [ ] `git status` clean on `main`.
- [ ] `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` — green.
- [ ] CI green on the latest `main` commit (`.github/workflows/test.yml`).
- [ ] Bump `version` in `pyproject.toml` and `__version__` in `src/__init__.py`.
      Keep them in lockstep; nothing reads from a single source today.
- [ ] Skim `README.md`, `CLAUDE.md`, and the Preferences dialog text for
      stale claims (this matters most after behavior changes).

## Fresh-machine smoke test

ccwork has never been installed on a clean box by anyone but the author.
Before tagging, do this on a throwaway Linux VM (Ubuntu 22.04 or 24.04 with
xorg or XWayland; X11 session preferred):

- [ ] `sudo apt install git python3 python3-venv xterm` (and `notify-send`
      via `libnotify-bin` if you want desktop notifications).
- [ ] Run the bootstrap one-liner from README against the tag candidate.
- [ ] Confirm `ccwork` launches; sidebar empty on first run.
- [ ] Add a repo via `Ctrl+O`. Open a terminal in it.
- [ ] Run `claude --version` inside the embedded xterm; confirm the wrapper
      passes through (you should see Anthropic's claude version, not an
      error from our wrapper).
- [ ] Run `claude` from a *new* git root inside the GUI — sidebar should
      auto-add it (RepoAdded ping).
- [ ] Trigger a Stop/Notification event; confirm sidebar status badge
      updates and (if enabled) `notify-send` fires.
- [ ] Click the 🔊 / 🔇 toolbutton in the top bar; confirm the
      Preferences "Show desktop notifications" checkbox flips to match
      and notify-send is suppressed when muted.
- [ ] Enable "Auto-arrange repos by recent Claude activity" with two or
      more repos; trigger Stop in the lower repo, then stop touching the
      sidebar — the row should bubble up to the top within ~3 s
      (2 s debounce + 0.8 s sidebar-quiet window).
- [ ] `Ctrl+O` the same repo twice — confirm rows show `(I)` and `(II)`,
      each with its own terminal. Remove `(II)`; the survivor's suffix
      should disappear. Restart the app and confirm both ids round-trip
      in `repos.json`.
- [ ] `./install.sh --uninstall` — confirm idempotent and that backups land
      in `~/.local/share/ccwork/backups/`.

## Tag and release

- [ ] `git tag -a v0.1.0 -m "ccwork v0.1.0"` (annotated).
- [ ] `git push origin v0.1.0`.
- [ ] Draft a GitHub Release for the tag. Body: 5–10 bullets of headline
      changes since the previous tag (or, for v0.1.0, the elevator pitch
      from README plus the Linux+X11/XWayland constraint stated up front).
- [ ] Pin the bootstrap one-liner in the release body so users have an
      install command they can paste from the release page itself.

## Out of scope for v0.1.0

- PyPI publication. The package isn't structured for `pip install ccwork`
  to be the recommended path — `bootstrap.sh` is. Revisit after v0.2.
- Wayland-native, macOS, Windows. Tracked in
  `docs/roadmap-cross-platform.md`.

## Post-release

- [ ] Open a tracking issue for whatever the smoke test surfaced.
- [ ] If the bootstrap line got fixed up during the smoke test, port the
      fix back to `bootstrap.sh` on `main` *before* announcing.
