"""Live check: text and signals reach the shell in an embedded xterm.

`TerminalHost.type_text` and `paste_clipboard` inject X key events through
XTEST; `send_suspend` sends SIGTSTP to the terminal's foreground process
group. A write to the PTY slave would only show as output, so this script
checks the real effect: a typed and a pasted command each write a file,
and a `sleep` job moves to the stopped state (ps STAT "T").

Starts its own Xvfb display (:97), so no keystroke reaches your desktop.
Run from the repo root:

    .venv/bin/python tests/live/check_terminal_input.py
"""
import os, subprocess, sys, tempfile, time

DISPLAY = ":97"
if os.environ.get("_CCWORK_INPUT_CHILD") != "1":
    xvfb = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1024x768x24"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        env = dict(os.environ, DISPLAY=DISPLAY, QT_QPA_PLATFORM="xcb", _CCWORK_INPUT_CHILD="1")
        sys.exit(subprocess.run([sys.executable, __file__], env=env, timeout=60).returncode)
    finally:
        xvfb.terminate()

sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PySide6.QtCore import QTimer
app = QApplication([])
from src.core import x11
from src.core.settings import XtermSettings
from src.ui.terminal_host import TerminalHost

work = tempfile.mkdtemp()
argv = [*XtermSettings().to_xterm_args(), "-e", "bash", "--norc", "-i"]
win = QWidget(); lay = QVBoxLayout(win)
host = TerminalHost(argv=argv, cwd=work, env={"PS1": "$ "})
lay.addWidget(host); win.resize(700, 400); win.show()
host.start()

def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)

def enter():
    host._xdisplay.press_combo((), 0xff0d)  # XK_Return

pump(3)
assert host._xterm_win, "xterm never embedded"
win.activateWindow(); pump(0.5)
results = {}

host.type_text("echo typed-ok > typed.txt"); enter(); pump(1.5)
results["type_text"] = open(f"{work}/typed.txt").read().strip() if os.path.exists(f"{work}/typed.txt") else None

QApplication.clipboard().setText("echo 'Pasted: OK \"q\"' > pasted.txt"); pump(0.5)
host.paste_clipboard(); pump(0.5); enter(); pump(1.5)
results["paste_clipboard"] = open(f"{work}/pasted.txt").read().strip() if os.path.exists(f"{work}/pasted.txt") else None

host.type_text("sleep 300"); enter(); pump(1.5)
sl = subprocess.run(["pgrep", "-n", "-f", "^sleep 300$"], capture_output=True, text=True).stdout.strip()
before = subprocess.run(["ps", "-o", "stat=", "-p", sl], capture_output=True, text=True).stdout.strip()
ok = host.send_suspend(); pump(1.0)
after = subprocess.run(["ps", "-o", "stat=", "-p", sl], capture_output=True, text=True).stdout.strip()
results["send_suspend"] = (ok, before, after)
print(results)
expected = {"type_text": "typed-ok", "paste_clipboard": 'Pasted: OK "q"'}
failed = [k for k, v in expected.items() if results[k] != v]
if results["send_suspend"][0] is not True or not results["send_suspend"][2].startswith("T"):
    failed.append("send_suspend")
if sl: os.kill(int(sl), 9)
host.stop(); pump(0.5)
print("FAIL: " + ", ".join(failed) if failed else "PASS")
sys.exit(1 if failed else 0)
