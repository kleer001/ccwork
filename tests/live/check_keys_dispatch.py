"""Live verification that the full shortcut surface dispatches.

Launches ccwork in a sandbox, focuses it, then injects each of the
five canonical shortcut combos through XTEST (xdotool) and asserts that each
produces a ``KeyGrabFilter DISPATCH`` log line (and, where applicable,
a visible dialog window). Modal dialogs are dismissed with `Esc` and
ccwork is re-focused between steps because KDE Plasma doesn't always
restore focus to the parent cleanly after a modal closes.

Use as a smoke check after touching the bindings table in
``MainWindow._install_global_keys`` — it covers the common breakage
shapes (modifier mask wrong, callback signature mismatch, modal
focus issues) in one run.
"""

from __future__ import annotations

import sys

import harness

# (xdotool key, the title of the dialog that it opens, or "")
COMBOS = (
    ("ctrl+shift+p", "Preferences"),
    ("ctrl+Tab", ""),          # cycle rows: a no-op with no rows, but it dispatches
    ("ctrl+shift+1", ""),      # row jump
    ("ctrl+shift+Tab", ""),    # cycle back
    ("ctrl+shift+o", "Add repo"),
)


def main() -> int:
    with harness.ccwork(harness.new_sandbox("keytest")) as app:
        line = next(l for l in app.log().splitlines() if "global keys:" in l)
        print(f"  startup: {line.strip()}")
        checks = {"grabs installed (platform xcb)": "shortcuts on MainWindow=" in line}
        for combo, dialog in COMBOS:
            before = app.dispatches()
            harness.key(combo, pause=0.6)
            checks[f"{combo} dispatch"] = app.dispatches() > before
            if dialog:
                checks[f"{combo} opens {dialog}"] = dialog.lower() in harness.windows().lower()
                harness.key("Escape", pause=0.3)
                app.focus()
        return harness.report(checks)


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
