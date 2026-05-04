"""Build the xterm argv for a given repo.

Isolates the "which command to run inside xterm" decision so the UI doesn't
need to know about shell selection or the user's claude launch preference.

Design note: ccwork drops into an interactive shell. Users type `claude`
(or anything else) themselves. The `claude` wrapper at bin/claude pings
the GUI socket with a RepoAdded event for unregistered git roots; it
otherwise execs the real claude untouched. For bash, we launch via
--rcfile bin/ccwork-bashrc to guarantee ccwork/bin wins on PATH regardless
of the user's .bashrc layout — see _inner_command.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from src.core.repo_store import Repo
from src.core.settings import XtermSettings


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
    gui_marker: bool = True,
) -> SessionSpec:
    """Return the xterm command pieces for this repo.

    The returned `argv` is everything that should follow `-into <winId>` in
    the xterm command line: tuning flags from `xterm_settings`, then `-e
    <shell> -i`.

    `gui_marker` sets CCWORK_GUI=1 so the `claude` wrapper can tell it is
    being invoked from inside the GUI and ping the hook socket.
    """
    inner_cmd = _inner_command()
    xterm_flags = (xterm_settings or XtermSettings()).to_xterm_args()

    # xterm args that run inside it come after `-e`. Everything after -e is
    # taken as-is by xterm — no shell is interposed — so we pass argv pieces.
    xterm_tail = [*xterm_flags, "-e", *inner_cmd]

    env: dict[str, str] = {}
    if gui_marker:
        env["CCWORK_GUI"] = "1"

    return SessionSpec(argv=xterm_tail, cwd=repo.path, env=env)


def _inner_command() -> list[str]:
    """Argv of the thing xterm should run (after -e) — the user's shell.

    For bash, we launch with `--rcfile bin/ccwork-bashrc` so ccwork/bin is
    guaranteed to win on PATH after the user's .bashrc runs. Without this,
    a .bashrc that re-prepends another directory after the ccwork block
    (or one that doesn't source the ccwork block at all) bypasses the
    `claude` wrapper, and the GUI's RepoAdded ping is lost. For non-bash
    shells we drop in plain `-i`; users on zsh/fish need to handle PATH
    ordering themselves until we ship per-shell shims.
    """
    shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
    if os.path.basename(shell) == "bash":
        rcfile = _ccwork_bashrc_path()
        if rcfile is not None:
            return [shell, "--rcfile", rcfile, "-i"]
    return [shell, "-i"]


def _ccwork_bashrc_path() -> str | None:
    """Absolute path to bin/ccwork-bashrc, or None if missing.

    This file lives at <repo>/src/core/terminal_session.py; the shim is at
    <repo>/bin/ccwork-bashrc. Resolve relatively so the install dir can
    move without breaking.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.normpath(os.path.join(here, "..", "..", "bin", "ccwork-bashrc"))
    return candidate if os.path.isfile(candidate) else None
