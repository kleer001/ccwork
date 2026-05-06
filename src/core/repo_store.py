"""Persistent list of repos the GUI knows about.

On-disk format: `~/.config/ccwork/repos.json`

    {
      "version": 1,
      "repos": [
        {"id": "…", "path": "/home/x/repo", "instance": 0}
      ]
    }

Duplicate paths are allowed — each entry is a separate sidebar instance.
`id` (uuid4) is the stable identity; `instance` is the Roman-numeral suffix
(0 = no suffix, ≥1 = the I/II/III index shown next to the basename).

The store is a plain value object — it does not watch the file for external
edits. Reload by constructing a new instance.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 1


def default_config_path() -> Path:
    """Return `$XDG_CONFIG_HOME/ccwork/repos.json` (or `~/.config/...`)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "ccwork" / "repos.json"


# Standard greedy table for ASCII Roman numerals. Valid range: 1..3999.
_ROMAN_TABLE = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100,  "C"), (90,  "XC"), (50,  "L"), (40,  "XL"),
    (10,   "X"), (9,   "IX"), (5,   "V"), (4,   "IV"),
    (1,    "I"),
)


def to_roman(n: int) -> str:
    """Convert 1..3999 to a Roman numeral. Raises ValueError on out-of-range."""
    if not isinstance(n, int) or n < 1 or n > 3999:
        raise ValueError(f"to_roman: out of range (1..3999), got {n!r}")
    out: list[str] = []
    for v, sym in _ROMAN_TABLE:
        while n >= v:
            out.append(sym)
            n -= v
    return "".join(out)


@dataclass
class Repo:
    path: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    instance: int = 0

    @property
    def name(self) -> str:
        return os.path.basename(self.path.rstrip("/")) or self.path

    @property
    def display_name(self) -> str:
        if self.instance <= 0:
            return self.name
        return f"{self.name} ({to_roman(self.instance)})"


@dataclass
class RepoStore:
    """In-memory list of repos, backed by a JSON file.

    Call `load()` to populate from disk and `save()` to persist. Mutations are
    not auto-saved — callers decide when to flush.
    """

    config_path: Path = field(default_factory=default_config_path)
    repos: list[Repo] = field(default_factory=list)

    # ── disk ──

    def load(self) -> None:
        """Populate `self.repos` from `self.config_path`. Missing file → empty.

        A corrupt `repos.json` (invalid JSON from a mid-write crash) is
        treated as empty with a logged warning. Re-save overwrites it with
        a clean file. Missing `id` / `instance` on a row are filled in
        (back-compat with pre-duplicate-instance config files).
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
        out: list[Repo] = []
        for r in repos_raw:
            if not isinstance(r, dict) or "path" not in r:
                continue
            rid = r.get("id")
            if not isinstance(rid, str) or not rid:
                rid = uuid.uuid4().hex
            inst = r.get("instance", 0)
            if not isinstance(inst, int) or inst < 0:
                inst = 0
            out.append(Repo(path=str(r["path"]), id=rid, instance=inst))
        self.repos = out

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

    # ── lookup helpers ──

    def index_of(self, path: str) -> int:
        """First row whose realpath matches `path`, or -1."""
        resolved = os.path.realpath(path)
        for i, r in enumerate(self.repos):
            if os.path.realpath(r.path) == resolved:
                return i
        return -1

    def indices_of(self, path: str) -> list[int]:
        """All rows whose realpath matches `path`, in order."""
        resolved = os.path.realpath(path)
        return [i for i, r in enumerate(self.repos)
                if os.path.realpath(r.path) == resolved]

    def find_by_id(self, repo_id: str) -> Repo | None:
        for r in self.repos:
            if r.id == repo_id:
                return r
        return None

    def repos_for_path(self, path: str) -> list[Repo]:
        """All entries whose realpath matches `path` (zero, one, or many)."""
        return [self.repos[i] for i in self.indices_of(path)]

    # ── mutations ──

    def add(self, path: str) -> Repo:
        """Add a repo and return the new entry.

        Duplicates are allowed — each call appends a fresh row with a unique
        `id`. The `instance` (Roman-numeral suffix) is assigned per the
        sticky-while-duplicated rule:

        - 0 existing for this path → new instance = 0 (no suffix)
        - 1 existing with instance == 0 → promote it to 1, new is 2 (sequence
          restarts when we re-enter the duplicate state)
        - otherwise → new instance = max(existing instance) + 1 (gaps from
          prior removals are preserved)
        """
        resolved = os.path.realpath(path)
        siblings = [self.repos[i] for i in self.indices_of(resolved)]
        if not siblings:
            new_inst = 0
        elif len(siblings) == 1 and siblings[0].instance == 0:
            siblings[0].instance = 1
            new_inst = 2
        else:
            new_inst = max(s.instance for s in siblings) + 1
        repo = Repo(path=resolved, instance=new_inst)
        self.repos.append(repo)
        return repo

    def remove_by_id(self, repo_id: str) -> bool:
        """Remove the repo with this id. Returns True if removed.

        After removal, if exactly one entry remains for that path, its
        `instance` is reset to 0 so the bare basename is shown again.
        """
        for i, r in enumerate(self.repos):
            if r.id == repo_id:
                resolved = os.path.realpath(r.path)
                self.repos.pop(i)
                survivors = [self.repos[j] for j in self.indices_of(resolved)]
                if len(survivors) == 1:
                    survivors[0].instance = 0
                return True
        return False

    def move_by_id(self, repo_id: str, new_index: int) -> bool:
        """Reorder: move the repo with `repo_id` to `new_index`."""
        for i, r in enumerate(self.repos):
            if r.id == repo_id:
                repo = self.repos.pop(i)
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
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    branch = r.stdout.strip()
    return branch or None
