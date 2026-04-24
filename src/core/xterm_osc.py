"""Live settings application via xterm OSC escape sequences.

xterm reads a handful of terminal-output control codes that reconfigure
itself at runtime without a restart. We use three:

    OSC 10 ; <color> ST    — text foreground
    OSC 11 ; <color> ST    — text background
    OSC 12 ; <color> ST    — cursor color
    OSC 50 ; <face> ST     — font face (may be disabled by allowFontOps)

We deliver them by writing to the xterm's child-shell PTY slave
(`/dev/pts/N`). Data written there flows slave → master → xterm, which
consumes OSC codes instead of displaying them. This is the same channel
the `xtermcontrol` utility uses; we just avoid the binary dependency.

Settings that xterm reads only at startup (scrollback, scrollbar, faceSize
in some builds, -xrm options) cannot be applied live — the caller must
respawn the terminal. `apply_live()` returns the list of knobs it could
NOT apply so callers can prompt the user.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from src.core.settings import XtermSettings


log = logging.getLogger(__name__)


ESC = "\x1b"
BEL = "\x07"


def osc(code: int, value: str) -> str:
    """Build one OSC sequence terminated by BEL (widest xterm compat)."""
    return f"{ESC}]{code};{value}{BEL}"


def find_child_pty(xterm_pid: int) -> Path | None:
    """Return the `/dev/pts/N` of the xterm's first child process, if any.

    Works via /proc; returns None on non-Linux or if the child has already
    exited.
    """
    try:
        children_file = Path(f"/proc/{xterm_pid}/task/{xterm_pid}/children")
        raw = children_file.read_text().split()
    except (FileNotFoundError, PermissionError, OSError):
        return None
    if not raw:
        return None
    for child_pid in raw:
        try:
            target = os.readlink(f"/proc/{child_pid}/fd/0")
        except (FileNotFoundError, PermissionError, OSError):
            continue
        if target.startswith("/dev/pts/"):
            return Path(target)
    return None


def write_to_pty(pty_path: Path, payload: str) -> bool:
    """Write `payload` to the PTY slave. Returns True on success.

    Uses O_WRONLY without O_CREAT so we never accidentally create a regular
    file when pointed at a typo'd path — we only want to write to an
    already-existing PTY node.
    """
    try:
        fd = os.open(str(pty_path), os.O_WRONLY | os.O_NOCTTY)
    except (FileNotFoundError, PermissionError, OSError) as e:
        log.warning("could not open %s: %s", pty_path, e)
        return False
    try:
        os.write(fd, payload.encode("utf-8", errors="replace"))
        return True
    except OSError as e:
        log.warning("could not write OSC to %s: %s", pty_path, e)
        return False
    finally:
        os.close(fd)


def apply_live(xterm_pid: int, settings: XtermSettings) -> list[str]:
    """Apply what we can of `settings` to a running xterm.

    Returns the list of settings fields that could NOT be applied live
    (either because xterm reads them only at startup, or because we
    couldn't reach the child PTY).
    """
    unapplied: list[str] = []

    pty = find_child_pty(xterm_pid)
    if pty is None:
        return [
            "font_family", "font_size", "bg", "fg",
            "scrollback", "scrollbar", "jump_scroll", "extra_args",
        ]

    # Colors — universally supported.
    parts: list[str] = []
    parts.append(osc(10, settings.fg))   # foreground
    parts.append(osc(11, settings.bg))   # background
    parts.append(osc(12, settings.fg))   # cursor (mirror fg)
    # Font face — OSC 50. Some xterm builds disable this via allowFontOps;
    # if it's off, xterm quietly ignores the sequence.
    parts.append(osc(50, settings.font_family))

    if not write_to_pty(pty, "".join(parts)):
        return [
            "font_family", "font_size", "bg", "fg",
            "scrollback", "scrollbar", "jump_scroll", "extra_args",
        ]

    # These require a full xterm restart:
    # - font_size: OSC 50 carries only a face name, not a size; xterm's
    #   face size is fixed at startup by -fs / faceSize resource.
    # - scrollback: saveLines resource is read once at startup.
    # - scrollbar: -sb/-rightbar can't be toggled via OSC.
    # - jump_scroll: -j is a startup flag.
    # - extra_args: by definition, startup-only.
    unapplied.extend(["font_size", "scrollback", "scrollbar", "jump_scroll", "extra_args"])
    return unapplied
