"""Copy the source folder's small ignored files into a new worktree
(docs/specs/worktree.md 5.4), and the report that its first terminal prints.

Wholly ignored folders (`.venv/`, `node_modules/`, `tmp/`) stay behind, and
so do files over `COPY_MAX_BYTES`, symbolic links, and Claude Code's
`.claude/settings.local.json`, which applies in every worktree already.
"""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass, field

from src.core.worktree import ignored_entries

COPY_MAX_BYTES = 1024 * 1024
CLAUDE_LOCAL_SETTINGS = ".claude/settings.local.json"
# Names the report lists per section before "and N more". The report goes
# to the terminal in an env var, which Linux limits to 128 KiB.
REPORT_LIST_MAX = 10


@dataclass
class CopyReport:
    copied: int = 0
    skipped: list[tuple[str, int | None]] = field(default_factory=list)  # size None: a link
    failed: list[tuple[str, str]] = field(default_factory=list)          # (name, error)

    def text(self) -> str:
        """The lines the new terminal prints; "" when there was nothing to copy."""
        if not (self.copied or self.skipped or self.failed):
            return ""
        lines = [f"Copied {self.copied} ignored file{'' if self.copied == 1 else 's'}."]
        if self.skipped:
            lines.append("Not copied (over 1 MiB or a link):")
            shown = [(_printable(name), size) for name, size in self.skipped[:REPORT_LIST_MAX]]
            width = max(len(name) for name, _ in shown) + 3
            lines += [f"  {name:<{width}}{'link' if size is None else _size_text(size)}"
                      for name, size in shown]
            lines += _more(self.skipped, "  and {} more")
        lines += [f"Could not copy {_printable(name)}: {_printable(error)}"
                  for name, error in self.failed[:REPORT_LIST_MAX]]
        lines += _more(self.failed, "Could not copy {} more files.")
        return "\n".join(lines)


def _more(items: list, line: str) -> list[str]:
    """`line` with the count of the items past `REPORT_LIST_MAX`, if any."""
    rest = len(items) - REPORT_LIST_MAX
    return [line.format(rest)] if rest > 0 else []


def _printable(text: str) -> str:
    """`text` with each control character as `?`, so a file name cannot send
    escape sequences to the terminal."""
    return "".join(c if c.isprintable() else "?" for c in text)


def _size_text(size: int) -> str:
    """A decimal size with two or three digits: `6.9 GB`, `130 MB`."""
    value, unit = float(size), "B"
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            break
        value /= 1000
    return f"{value:.1f} {unit}" if value < 10 and unit != "B" else f"{value:.0f} {unit}"


def copy_ignored(src: str, dst: str) -> CopyReport:
    """Copy each ignored file of `src` of `COPY_MAX_BYTES` or less to the same
    place in `dst`, with its mode and times. A failed copy is reported, and
    the other files go on."""
    report = CopyReport()
    for name in ignored_entries(src):
        if name.endswith("/") or name == CLAUDE_LOCAL_SETTINGS:
            continue
        path = os.path.join(src, name)
        try:
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode):
                report.skipped.append((name, None))
                continue
            if st.st_size > COPY_MAX_BYTES:
                report.skipped.append((name, st.st_size))
                continue
            target = os.path.join(dst, name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(path, target)
        except OSError as e:
            report.failed.append((name, e.strerror or str(e)))
            continue
        report.copied += 1
    return report
