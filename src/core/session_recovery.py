"""Crash-recovery tracking for Claude Code sessions.

ccwork can't resurrect a dead PTY, but it can remember which Claude
conversations were open so that, after an unclean shutdown, the splash
screen can offer their session IDs for `claude --resume`.

State lives in `~/.config/ccwork/open_sessions.json`:

    {
      "open":     {<repo path>: {"id": <uuid>, "name": <label>}},
      "recovery": {<repo path>: {"id": <uuid>, "name": <label>}}
    }

`open`     — sessions believed live *right now*. Upserted as hook events
             arrive, dropped on SessionEnd / terminal exit, and the whole
             bucket emptied on a clean quit.
`recovery` — the crash-banner snapshot. At startup any leftover `open`
             entries (a clean quit would have emptied them, so their
             presence means the last run died) are folded in here. It
             persists across launches until the user dismisses the banner.

The file lives in the persistent config dir, not `$XDG_RUNTIME_DIR` — the
latter is tmpfs and is wiped on reboot, which would lose the power-loss
case (the one most worth catching).

Keyed by repo path: duplicate sidebar rows share a path, so they collapse
to one entry (last writer wins), consistent with the rest of ccwork's
path-keyed hook state.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


def default_path() -> Path:
    """Return `$XDG_CONFIG_HOME/ccwork/open_sessions.json` (or `~/.config/...`)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "ccwork" / "open_sessions.json"


def _load(path: Path) -> dict:
    """Read the state doc. Missing or corrupt → empty buckets — a
    half-written file from a crash must never break startup."""
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return {"open": {}, "recovery": {}}
    except (ValueError, OSError) as e:
        log.warning("%s unreadable (%s) — ignoring", path, e)
        return {"open": {}, "recovery": {}}
    open_b = raw.get("open") if isinstance(raw.get("open"), dict) else {}
    rec_b = raw.get("recovery") if isinstance(raw.get("recovery"), dict) else {}
    return {"open": open_b, "recovery": rec_b}


def _save(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n")
    os.replace(tmp, path)


def record_open(repo_path: str, session_id: str, name: str,
                path: Path | None = None) -> None:
    """Mark a session live. Idempotent: a no-op (no disk write) when this
    path already maps to the same id and carries no stale recovery entry,
    so re-calling on every hook event of a turn costs one read, not a
    write. A fresh session also drops any recovery entry for this path —
    the user has clearly moved on from the crash."""
    p = path or default_path()
    doc = _load(p)
    existing = doc["open"].get(repo_path)
    if (existing and existing.get("id") == session_id
            and repo_path not in doc["recovery"]):
        return
    doc["open"][repo_path] = {"id": session_id, "name": name}
    doc["recovery"].pop(repo_path, None)
    _save(p, doc)


def clear_open(repo_path: str, path: Path | None = None) -> None:
    """Drop a single live session (clean SessionEnd or terminal exit)."""
    p = path or default_path()
    doc = _load(p)
    if doc["open"].pop(repo_path, None) is not None:
        _save(p, doc)


def clear_all_open(path: Path | None = None) -> None:
    """Empty the live bucket on a clean quit. Leaves recovery untouched."""
    p = path or default_path()
    doc = _load(p)
    if doc["open"]:
        doc["open"] = {}
        _save(p, doc)


def promote_crashes(path: Path | None = None) -> list[dict]:
    """Startup hook: fold any leftover live sessions into recovery (their
    survival past a clean quit means the last run died), empty the live
    bucket, and return the recovery entries for the banner as a list of
    {"path", "name", "id"} dicts (possibly empty)."""
    p = path or default_path()
    doc = _load(p)
    if doc["open"]:
        doc["recovery"].update(doc["open"])
        doc["open"] = {}
        _save(p, doc)
    return [
        {"path": rp, "name": e.get("name", rp), "id": e.get("id", "")}
        for rp, e in doc["recovery"].items()
        if e.get("id")
    ]


def dismiss(path: Path | None = None) -> None:
    """Clear the recovery snapshot — the user dismissed the banner."""
    p = path or default_path()
    doc = _load(p)
    if doc["recovery"]:
        doc["recovery"] = {}
        _save(p, doc)
