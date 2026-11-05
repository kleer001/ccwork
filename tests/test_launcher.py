"""bin/ccwork: it starts the checkout that holds it, also through a link."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "bin" / "ccwork"


def test_the_launcher_runs_its_own_checkout(tmp_path: Path):
    checkout = tmp_path / "ccwork-fix-a"
    (checkout / "bin").mkdir(parents=True)
    shutil.copy2(LAUNCHER, checkout / "bin" / "ccwork")
    python = checkout / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/sh\necho "$PWD $*"\n')
    python.chmod(0o755)
    link = tmp_path / "on-path" / "ccwork"
    link.parent.mkdir()
    link.symlink_to(checkout / "bin" / "ccwork")

    # When the launcher starts the wrong checkout, that ccwork runs offscreen
    # on an empty config, away from the desktop ccwork, until the timeout.
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "config"),
           "XDG_RUNTIME_DIR": os.environ["XDG_RUNTIME_DIR"], "QT_QPA_PLATFORM": "offscreen"}
    out = subprocess.run([str(link), "--x"], cwd=tmp_path, env=env, capture_output=True, text=True,
                         check=True, timeout=10)

    assert out.stdout.strip() == f"{checkout} -m src.main --x"
