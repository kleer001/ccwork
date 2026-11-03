"""The dependency setup that a new worktree's first terminal runs
(docs/specs/worktree.md 5.5): a venv like the source folder's, and the
install command of its node lock file. ccwork passes the commands in
`CCWORK_SETUP_CMD`, and `bin/ccwork-bashrc` runs them once, in view.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from src.core.worktree import GitError, git_dir

VENV_NAMES = (".venv", "venv")
# `python -m venv` writes `version`; `uv venv` writes `version_info`.
VENV_VERSION_KEYS = ("version", "version_info")
NODE_INSTALLS = (
    ("package-lock.json", "npm ci"),
    ("pnpm-lock.yaml", "pnpm install --frozen-lockfile"),
    ("yarn.lock", "yarn install --frozen-lockfile"),
)
UV_MISSING = "uv not found: no venv made"
FREEZE_FILE = "ccwork-freeze.txt"
UV_FREEZE_TIMEOUT_S = 30


def setup_commands(src: str, dst: str) -> str:
    """Shell commands that rebuild `src`'s venv and node_modules in `dst`,
    one line per tool; "" when nothing installs. With a venv and no
    `uv.lock`, it writes the source venv's freeze into `dst`'s git dir. It
    does not raise: a failure becomes an `echo` of the error, so it shows in
    the row's terminal (docs/specs/worktree.md 5.3)."""
    steps = []
    venv = _source_venv(src)
    if venv:
        steps.append(_venv_step(src, dst, *venv))
    if os.path.isdir(os.path.join(src, "node_modules")):
        node = next((cmd for lock, cmd in NODE_INSTALLS
                     if os.path.isfile(os.path.join(src, lock))), None)
        if node:
            steps.append(node)
    return "\n".join(steps)


def _source_venv(src: str) -> tuple[str, str] | None:
    """(folder name, Python version) of the first venv folder of `src` whose
    `pyvenv.cfg` names a version."""
    for name in VENV_NAMES:
        cfg = os.path.join(src, name, "pyvenv.cfg")
        if not os.path.isfile(cfg):
            continue
        for line in Path(cfg).read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in VENV_VERSION_KEYS:
                return name, value.strip()
    return None


def _venv_step(src: str, dst: str, name: str, version: str) -> str:
    uv = shutil.which("uv")
    if uv is None:
        return f"echo {shlex.quote(UV_MISSING)}"
    q = shlex.quote
    target = os.path.join(dst, name)
    make = f"{q(uv)} venv --python {q(version)} {q(target)}"
    if os.path.isfile(os.path.join(src, "uv.lock")):
        return f"{make} && VIRTUAL_ENV={q(target)} {q(uv)} sync --active"
    try:
        r = subprocess.run([uv, "pip", "freeze", "--python", os.path.join(src, name, "bin", "python")],
                           capture_output=True, text=True, timeout=UV_FREEZE_TIMEOUT_S)
        if r.returncode != 0:
            return f"echo {q('uv pip freeze failed: ' + r.stderr.strip())}"
        # The worktree's private git dir: `git worktree remove` deletes it too.
        freeze = os.path.join(git_dir(dst), FREEZE_FILE)
        Path(freeze).write_text(rewrite_freeze(r.stdout, src, dst))
    except (subprocess.TimeoutExpired, GitError, OSError) as e:
        return f"echo {q(f'Could not make the venv: {e}')}"
    return f"{make} && {q(uv)} pip install --python {q(os.path.join(target, 'bin', 'python'))} -r {q(freeze)}"


def rewrite_freeze(text: str, src: str, dst: str) -> str:
    """`uv pip freeze` output with each editable entry inside `src` moved to
    the same place in `dst`. Other lines do not change."""
    src_url, dst_url = Path(src).as_uri(), Path(dst).as_uri()
    lines = []
    for line in text.splitlines():
        url = line[3:] if line.startswith("-e ") else ""
        if url == src_url or url.startswith(src_url + "/"):
            line = "-e " + dst_url + url[len(src_url):]
        lines.append(line)
    return "".join(f"{line}\n" for line in lines)
