"""Live verification that F1 opens the keyboard-shortcuts dialog.

Launches ccwork, focuses it, injects F1 via XTest, then verifies:
  - A new `KeyGrabFilter DISPATCH` entry appears in the log.
  - `wmctrl -l` reports a window titled `Keyboard shortcuts`.

The visible-window check guards against the dispatch firing but the
callback erroring out silently — both must hold for the user-visible
behavior to be correct.
"""

from __future__ import annotations

import sys

import harness


def main() -> int:
    with harness.ccwork(harness.new_sandbox("f1")) as app:
        before = app.dispatches()
        harness.key("F1", pause=0.6)
        return harness.report({
            "F1 dispatch fired": app.dispatches() > before,
            "Keyboard shortcuts window visible": "Keyboard shortcuts" in harness.windows(),
        })


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
