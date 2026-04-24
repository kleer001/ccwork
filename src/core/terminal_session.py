"""Build the xterm argv for a given repo.

Isolates the "which command to run inside xterm" decision so the UI doesn't
need to know about tmux, Claude resume, or shell fallback.
"""

from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import dataclass

from src.core import claude_slug
from src.core.repo_store import Repo
from src.core.settings import XtermSettings


def tmux_session_name(path: str) -> str:
    """Derive a unique-but-readable tmux session name for a repo path.

    Uses the same /_./ → - substitution Claude Code uses, then prefixes with
    ccwork- so it doesn't collide with the user's own sessions.
    """
    return "ccwork-" + claude_slug.slug_for_path(path).lstrip("-")


@dataclass
class SessionSpec:
    """What to run inside xterm for a repo.

    Consumers pass `argv` to `TerminalHost(argv=..., cwd=..., env=...)`.
    """
    argv: list[str]
    cwd: str
    env: dict[str, str]


def build_session(
    repo: Repo,
    *,
    xterm_settings: XtermSettings | None = None,
    auto_resume: bool = True,
    gui_marker: bool = True,
) -> SessionSpec:
    """Return the xterm command pieces for this repo.

    The returned `argv` is everything that should follow `-into <winId>` in
    the xterm command line: tuning flags from `xterm_settings`, then `-e
    <inner_cmd ...>`.

    `auto_resume` controls the Claude `--continue` shortcut: if a transcript
    exists for the repo's project, the terminal launches claude already
    continued. Otherwise it drops into `$SHELL -i` and the user types
    `claude` themselves (which goes through our wrapper).

    `gui_marker` sets CCWORK_GUI=1 so the `claude` wrapper can tell it is
    being invoked from inside the GUI and ping the hook socket.
    """
    inner_cmd = _inner_command(repo, auto_resume=auto_resume)
    xterm_flags = (xterm_settings or XtermSettings()).to_xterm_args()

    # xterm args that run inside it come after `-e`. Everything after -e is
    # taken as-is by xterm — no shell is interposed — so we pass argv pieces.
    xterm_tail = [*xterm_flags, "-e", *inner_cmd]

    env: dict[str, str] = {}
    if gui_marker:
        env["CCWORK_GUI"] = "1"

    return SessionSpec(argv=xterm_tail, cwd=repo.path, env=env)


def _inner_command(repo: Repo, *, auto_resume: bool) -> list[str]:
    """Argv of the thing xterm should run (after -e)."""
    shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"

    # 1. Claude --continue directly when we have a transcript and auto-resume
    #    is on. We let the user's `claude` wrapper handle the exec; it lives
    #    on PATH (the installer puts bin/ on PATH).
    if auto_resume and claude_slug.has_transcript(repo.path):
        base = ["claude", "--continue"]
    else:
        # Drop into an interactive shell. The user types `claude` to start.
        base = [shell, "-i"]

    if repo.persist:
        # tmux new -A -s <name> -- <cmd>  attaches if session exists else
        # creates it, then runs `cmd` as the initial command. Without --
        # tmux would try to interpret our flags.
        tmux = shutil.which("tmux")
        if tmux:
            return [
                tmux, "new", "-A", "-s", tmux_session_name(repo.path),
                shlex.join(base),
            ]
        # tmux missing but persist=True: degrade gracefully rather than fail.
    return base
