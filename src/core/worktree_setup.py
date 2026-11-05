"""The dependency setup that a new worktree's first terminal runs
(docs/specs/worktree.md 5.5): a venv like the source folder's, with the
dependencies that the worktree declares, and the install command of its node
lock file. ccwork passes the commands in `CCWORK_SETUP_CMD`, and
`bin/ccwork-bashrc` runs them once, in view.
"""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path

VENV_NAMES = (".venv", "venv")
# `python -m venv` writes `version`; `uv venv` writes `version_info`.
VENV_VERSION_KEYS = ("version", "version_info")
# The first file that the worktree has picks the install.
PYTHON_INSTALLS = (
    ("uv.lock", "VIRTUAL_ENV={venv} {uv} sync --active"),
    ("requirements.txt", "{uv} pip install --python {python} -r {file}"),
    ("pyproject.toml", "{uv} pip install --python {python} -r {file} --all-extras"),
)
NODE_INSTALLS = (
    ("package-lock.json", "npm ci"),
    ("pnpm-lock.yaml", "pnpm install --frozen-lockfile"),
    ("yarn.lock", "yarn install --frozen-lockfile"),
)
UV_MISSING = "uv not found: no venv made"


def setup_commands(src: str, dst: str) -> str:
    """Shell commands that rebuild `src`'s venv and node_modules in `dst`,
    one line per tool; "" when nothing installs. The files of `dst` pick
    each install command."""
    steps = []
    venv = _source_venv(src)
    if venv:
        steps.append(_venv_step(dst, *venv))
    if os.path.isdir(os.path.join(src, "node_modules")):
        node = _first_install(dst, NODE_INSTALLS)
        if node:
            steps.append(node[1])
    return "\n".join(steps)


def _first_install(folder: str, installs: tuple[tuple[str, str], ...]) -> tuple[str, str] | None:
    """(path, command) of the first file of `installs` that `folder` has."""
    return next(((os.path.join(folder, name), cmd) for name, cmd in installs
                 if os.path.isfile(os.path.join(folder, name))), None)


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


def _venv_step(dst: str, name: str, version: str) -> str:
    """Make the venv, then install what `dst` declares. With no declaration,
    the venv stays empty."""
    uv = shutil.which("uv")
    if uv is None:
        return f"echo {shlex.quote(UV_MISSING)}"
    q = shlex.quote
    venv = os.path.join(dst, name)
    make = f"{q(uv)} venv --python {q(version)} {q(venv)}"
    install = _first_install(dst, PYTHON_INSTALLS)
    if install is None:
        return make
    path, cmd = install
    return f"{make} && " + cmd.format(uv=q(uv), venv=q(venv), file=q(path),
                                      python=q(os.path.join(venv, "bin", "python")))
