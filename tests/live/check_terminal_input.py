"""Live check: text and signals reach the shell in an embedded xterm.

`TerminalHost.type_text` and `paste_clipboard` inject X key events through
XTEST; `send_suspend` sends SIGTSTP to the terminal's foreground process
group. A write to the PTY slave would only show as output, so this script
checks the real effect: a typed and a pasted command each write a file,
and a `sleep` job moves to the stopped state (ps STAT "T").

Runs on its own Xvfb display (`harness.run_on_xvfb`). It launches no ccwork:
it embeds one `TerminalHost` in a plain window.

    .venv/bin/python tests/live/check_terminal_input.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import harness


def main() -> int:
    sys.path.insert(0, str(harness.REPO))
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication([])
    from src.core.settings import XtermSettings
    from src.ui.terminal_host import TerminalHost

    work = str(harness.new_sandbox("terminal"))
    argv = [*XtermSettings().to_xterm_args(), "-e", "bash", "--norc", "-i"]
    win = QWidget()
    lay = QVBoxLayout(win)
    host = TerminalHost(argv=argv, cwd=work, env={"PS1": "$ "})
    lay.addWidget(host)
    win.resize(700, 400)
    win.show()
    host.start()

    def pump(sec: float) -> None:
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    def enter() -> None:
        host._xdisplay.press_combo((), 0xff0d)  # XK_Return

    def written(name: str) -> str | None:
        path = os.path.join(work, name)
        return open(path).read().strip() if os.path.exists(path) else None

    def stat(pid: str) -> str:
        return subprocess.run(["ps", "-o", "stat=", "-p", pid], capture_output=True, text=True).stdout.strip()

    pump(3)
    assert host._xterm_win, "xterm never embedded"
    win.activateWindow()
    pump(0.5)

    host.type_text("echo typed-ok > typed.txt")
    enter()
    pump(1.5)
    QApplication.clipboard().setText("echo 'Pasted: OK \"q\"' > pasted.txt")
    pump(0.5)
    host.paste_clipboard()
    pump(0.5)
    enter()
    pump(1.5)

    host.type_text("sleep 300")
    enter()
    pump(1.5)
    sleep_pid = subprocess.run(["pgrep", "-n", "-f", "^sleep 300$"], capture_output=True, text=True).stdout.strip()
    before = stat(sleep_pid)
    suspended = host.send_suspend()
    pump(1.0)
    after = stat(sleep_pid)
    print(f"sleep state: {before} -> {after}")
    checks = {
        "type_text": written("typed.txt") == "typed-ok",
        "paste_clipboard": written("pasted.txt") == 'Pasted: OK "q"',
        "send_suspend": suspended is True and after.startswith("T"),
    }
    if sleep_pid:
        os.kill(int(sleep_pid), 9)
    host.stop()
    pump(0.5)
    return harness.report(checks)


if __name__ == "__main__":
    harness.run_on_xvfb()
    sys.exit(main())
