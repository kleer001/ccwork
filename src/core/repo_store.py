"""Persistent list of repos the GUI knows about.

On-disk format: `~/.config/ccwork/repos.json`

    {
      "version": 1,
      "repos": [
        {"path": "/home/x/repo"}
      ]
    }

The store is a plain value object — it does not watch the file for external
edits. Reload by constructing a new instance.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1


def default_config_path() -> Path:
    """Return `$XDG_CONFIG_HOME/ccwork/repos.json` (or `~/.config/...`)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "ccwork" / "repos.json"


@dataclass
class Repo:
    path: str

    @property
    def name(self) -> str:
        return os.path.basename(self.path.rstrip("/")) or self.path


@dataclass
class RepoStore:
    """In-memory list of repos, backed by a JSON file.

    Call `load()` to populate from disk and `save()` to persist. Mutations are
    not auto-saved — callers decide when to flush.
    """

    config_path: Path = field(default_factory=default_config_path)
    repos: list[Repo] = field(default_factory=list)

    def load(self) -> None:
        """Populate `self.repos` from `self.config_path`. Missing file → empty.

        A corrupt `repos.json` (invalid JSON from a mid-write crash) is
        treated as empty with a logged warning. Re-save overwrites it with
        a clean file.
        """
        if not self.config_path.exists():
            self.repos = []
            return
        raw = self.config_path.read_text()
        if not raw.strip():
            self.repos = []
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            import logging
            logging.getLogger(__name__).warning(
                "%s is not valid JSON (%s) — starting with empty repo list",
                self.config_path, e,
            )
            self.repos = []
            return
        if not isinstance(data, dict):
            raise ValueError(f"{self.config_path}: expected object, got {type(data).__name__}")
        repos_raw = data.get("repos", [])
        if not isinstance(repos_raw, list):
            raise ValueError(f"{self.config_path}: 'repos' must be a list")
        self.repos = [
            Repo(path=str(r["path"]))
            for r in repos_raw
            if isinstance(r, dict) and "path" in r
        ]

    def save(self) -> None:
        """Write `self.repos` to `self.config_path` atomically."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SCHEMA_VERSION,
            "repos": [asdict(r) for r in self.repos],
        }
        tmp = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n")
        os.replace(tmp, self.config_path)

    def add(self, path: str) -> bool:
        """Add a repo. Returns True if added, False if already present.

        The path is normalized with `os.path.realpath` before comparison so
        symlinks and trailing slashes don't create duplicates.
        """
        resolved = os.path.realpath(path)
        if any(os.path.realpath(r.path) == resolved for r in self.repos):
            return False
        self.repos.append(Repo(path=resolved))
        return True

    def remove(self, path: str) -> bool:
        """Remove a repo by path. Returns True if removed."""
        resolved = os.path.realpath(path)
        before = len(self.repos)
        self.repos = [r for r in self.repos if os.path.realpath(r.path) != resolved]
        return len(self.repos) != before

    def move(self, path: str, new_index: int) -> bool:
        """Reorder: move the repo with `path` to `new_index`."""
        resolved = os.path.realpath(path)
        for i, r in enumerate(self.repos):
            if os.path.realpath(r.path) == resolved:
                repo = self.repos.pop(i)
                # Clamp so callers passing len(self.repos) still work
                new_index = max(0, min(new_index, len(self.repos)))
                self.repos.insert(new_index, repo)
                return True
        return False

    def __iter__(self) -> Iterator[Repo]:
        return iter(self.repos)

    def __len__(self) -> int:
        return len(self.repos)


def is_git_root(path: str | os.PathLike[str]) -> bool:
    """True iff `path` is the top level of a git working tree."""
    try:
        r = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if r.returncode != 0:
        return False
    top = r.stdout.strip()
    if not top:
        return False
    return os.path.realpath(top) == os.path.realpath(str(path))


def current_branch(path: str | os.PathLike[str]) -> str | None:
    """Return the current branch name, or None if detached/not-a-repo.

    Prefers `symbolic-ref --short HEAD`. On detached HEAD returns None —
    callers that want a fallback can call this + `short_sha` themselves.
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(path), "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    branch = r.stdout.strip()
    return branch or None
