# Security Policy

## Supported versions

ccwork is pre-1.0 and ships from `main`. Security fixes land on `main` and
in the next tagged release. Please test against the latest `main` before
reporting.

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately using either:

- GitHub's [private vulnerability reporting](https://github.com/kleer001/ccwork/security/advisories/new)
  (Security → Report a vulnerability), or
- email **kleer001code@gmail.com** with `ccwork security` in the subject.

Please include:

- affected version / commit,
- your distro and whether you're on X11 or XWayland,
- reproduction steps and impact.

We aim to acknowledge reports within a few days and will keep you updated as
we work on a fix. We'll credit you in the release notes unless you'd prefer
to stay anonymous.

## Sensitive surfaces to be aware of

If you're auditing ccwork, these are the components that touch the wider
system and are the most security-relevant:

- **Hook socket** (`src/core/hook_server.py`) — a `QLocalServer` listening
  at `$XDG_RUNTIME_DIR/ccwork/ccwork.sock`. It accepts newline-delimited
  JSON from local clients; malformed input is logged and dropped, never
  raised. It is a singleton and refuses to steal a live instance's path.
- **`bin/claude`** — a `PATH`-shadow wrapper that pings the socket for
  unregistered git roots, then `exec`s the real `claude` with the user's
  args untouched.
- **`bin/ccwork-hook-sink`** — wired into Claude Code's hooks; gated by
  `CCWORK_GUI=1` so it is inert outside the ccwork GUI.
- **`install.sh` / `bootstrap.sh`** — write only under `$HOME`, back up
  every touched file, and support `--dry-run` and `--uninstall`.

ccwork has **no network calls and no telemetry** — the dashboard and stats
are computed locally from `git`.
