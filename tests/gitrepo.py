"""Git repos for tests: a git runner with a fixed identity, a commit, and a
new repo. Stdlib only, so the live checks in `tests/live/` use it too."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# The author and committer of each commit, whatever the user's git config.
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(*args: str, date: str | None = None, check: bool = True) -> str:
    """Run git with `IDENTITY` and no other inherited `GIT_*` variable, and
    give its stdout, stripped. `date` sets the author and committer dates."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")} | IDENTITY
    if date is not None:
        env |= {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    return subprocess.run(["git", *args], check=check, capture_output=True, text=True,
                          env=env).stdout.strip()


def commit(repo: Path, files: dict[str, str] | None = None, message: str = "commit",
           date: str | None = None) -> None:
    """Write `files` (name: text) into `repo`, stage each change, and commit."""
    for name, text in (files or {}).items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git("-C", str(repo), "add", "-A")
    git("-C", str(repo), "commit", "-qm", message, date=date)


def seed(path: Path, files: dict[str, str] | None = None, message: str = "seed") -> Path:
    """A new git repo at `path` on branch `main`, with one commit of `files`
    when they are given. Gives `path`."""
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-q", "-b", "main", str(path))
    if files:
        commit(path, files, message)
    return path
