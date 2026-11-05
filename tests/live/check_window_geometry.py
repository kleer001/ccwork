"""Live verification that window.geometry is persisted on Ctrl+Shift+Q.

Launches ccwork in a sandbox, focuses it, injects Ctrl+Shift+Q, then
reads the sandboxed ``settings.toml`` and asserts that
``[window].geometry`` contains a non-empty base64 string. End-to-end
proof that:

  - The Ctrl+Shift+Q binding still fires.
  - `closeEvent` reaches `_persist_window_state` past the (absent)
    working-session prompt.
  - `saveGeometry()` round-trips through `_window_to_toml` and lands
    on disk in the expected schema.
"""

from __future__ import annotations

import subprocess
import sys

import harness


def main() -> int:
    with harness.ccwork(harness.new_sandbox("geom")) as app:
        harness.key("ctrl+shift+q", pause=0)
        try:
            app.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("FAIL: ccwork did not exit after Ctrl+Shift+Q")
            return 2
        settings = app.config / "settings.toml"
        text = settings.read_text() if settings.exists() else ""
        # The geometry value should be non-empty after a clean quit.
        in_window = False
        geom_value = ""
        for line in text.splitlines():
            if line.strip() == "[window]":
                in_window = True
                continue
            if in_window and line.startswith("["):
                break
            if in_window and line.strip().startswith("geometry"):
                geom_value = line.split("=", 1)[1].strip().strip('"')
        print(f"geometry blob (len={len(geom_value)}): {geom_value[:40]}...")
        code = harness.report({
            "settings.toml written": settings.exists(),
            "[window] section": "[window]" in text,
            "geometry is a non-empty base64 blob": bool(geom_value),
        })
        if code:
            print("---settings.toml---")
            print(text)
        return code


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
