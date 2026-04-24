"""Claude Code project slug + transcript detection.

Mirrors the slug logic used by Claude Code itself and by the previous bash
`bin/claude` wrapper: the absolute project path has every `/`, `_`, and `.`
character replaced with `-`. The resulting string is a directory name under
`$CLAUDE_CONFIG_DIR/projects/` (default `~/.claude/projects/`) containing
`.jsonl` transcripts for that project.
"""

from __future__ import annotations

import os
from pathlib import Path


_SLUG_TRANSLATION = str.maketrans({"/": "-", "_": "-", ".": "-"})


def slug_for_path(path: str | os.PathLike[str]) -> str:
    """Return Claude Code's project-directory slug for an absolute path.

    The caller is responsible for passing an absolute, resolved path — the
    slug is path-shape-dependent, so `/home/x/repo` and `/home/x/repo/` and
    `./repo` all produce different slugs.
    """
    return str(path).translate(_SLUG_TRANSLATION)


def claude_config_dir() -> Path:
    """Return the Claude Code config directory (env or default)."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return Path(env)
    return Path.home() / ".claude"


def project_dir_for(path: str | os.PathLike[str]) -> Path:
    """Return the `<claude_config>/projects/<slug>` dir for a project path."""
    return claude_config_dir() / "projects" / slug_for_path(path)


def has_transcript(path: str | os.PathLike[str]) -> bool:
    """True iff at least one `.jsonl` transcript exists for this project."""
    pdir = project_dir_for(path)
    try:
        return any(pdir.glob("*.jsonl"))
    except OSError:
        return False
