"""Live verification that shortcuts are scoped to MainWindow focus.

The bug this guards against: a previous root-window XGrabKey caused
ccwork to intercept its shortcut combos *globally* — pressing
``Ctrl+Shift+P`` in Firefox popped ccwork's Preferences dialog. After
the 2026-05-13 fix, the grab is on MainWindow's own X window, so it
only activates when ccwork is in the focus chain.

Runs on its own Xvfb display (`harness.run_on_xvfb`).

Procedure:
  1. Launch ccwork.
  2. Focus another window (a plain xterm).
  3. Inject Ctrl+Shift+P via XTest.
  4. Assert: zero dispatch entries in the log (negative case).
  5. Focus ccwork.
  6. Inject Ctrl+Shift+P.
  7. Assert: one new dispatch entry (positive case).

If either assertion fails, the focus scoping regressed and shortcuts
are leaking outside ccwork's window again.
"""

from __future__ import annotations

import subprocess
import sys
import time

import harness

OTHER_TITLE = "live-other-window"


def main() -> int:
    with harness.other_window(OTHER_TITLE), harness.ccwork(harness.new_sandbox("focus")) as app:
        # ── NEGATIVE: focus the other xterm, inject Ctrl+Shift+P, expect 0 dispatch ──
        # A title match is safe here: the other window's title is fixed.
        subprocess.run(["wmctrl", "-a", OTHER_TITLE], check=True)
        time.sleep(0.6)
        before_neg = app.dispatches()
        harness.key("ctrl+shift+p", pause=0.6)
        after_neg = app.dispatches()
        neg_pass = after_neg == before_neg
        print(f"  ccwork unfocused + Ctrl+Shift+P → dispatches: "
              f"{before_neg} → {after_neg}  {'OK' if neg_pass else 'FAIL'}")

        # ── POSITIVE: focus ccwork, inject Ctrl+Shift+P, expect dispatch ──
        app.focus()
        before_pos = app.dispatches()
        harness.key("ctrl+shift+p", pause=0.6)
        after_pos = app.dispatches()
        pos_pass = after_pos > before_pos
        print(f"  ccwork focused + Ctrl+Shift+P → dispatches: "
              f"{before_pos} → {after_pos}  {'OK' if pos_pass else 'FAIL'}")
        return harness.report({"no dispatch while unfocused": neg_pass,
                               "a dispatch while focused": pos_pass})


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
