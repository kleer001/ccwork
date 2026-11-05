"""The shared parts of the live checks in `tests/live/`.

A check runs a real ccwork on its own X display, away from the desktop, and
drives it through xdotool (XTEST), so each key and text reaches the focused
window like a real keypress.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))  # for `src` and `tests`
from tests.gitrepo import git, seed  # noqa: E402

CHILD_FLAG = "_CCWORK_LIVE_CHILD"
EVIDENCE_VAR = "_CCWORK_LIVE_EVIDENCE"
RUNS = REPO / "tmp" / "live-runs"
SANDBOXES = REPO / "tmp" / "wt-sandbox"
# A session loads the CLAUDE.md files of the folders above it, and each
# sandbox is under the ccwork folder: the setting keeps ccwork's CLAUDE.md out.
CLAUDE = "claude --settings " + shlex.quote(json.dumps({"claudeMdExcludes": [str(REPO / "CLAUDE.md")]}))
SCREEN = "1280x900x24"  # MainWindow opens at 1280x820, plus the title bar
STARTUP_S = 10
CLAUDE_TIMEOUT_S = 120


def run_on_xvfb() -> None:
    """Start Xvfb on a free display (`-displayfd`) with openbox as the window
    manager, then run the calling script again inside it, and exit with its
    exit code. The child gets a temporary `XDG_RUNTIME_DIR`, so a ccwork that
    the script launches owns its own hook socket and never talks to the
    ccwork on the desktop. The D-Bus session address is `disabled:`, so
    desktop notifications stay off the desktop. The child's output also goes
    to `output.txt` in the evidence folder, line by line. Call it first in the
    script's `__main__` block."""
    if os.environ.get(CHILD_FLAG) == "1":
        return
    evidence = new_run_folder(RUNS, Path(sys.argv[0]).stem)
    read_fd, write_fd = os.pipe()
    xvfb = subprocess.Popen(
        ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", SCREEN, "-nolisten", "tcp"],
        pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(write_fd)
    with os.fdopen(read_fd) as f:
        number = f.readline().strip()
    if not number:
        xvfb.terminate()
        sys.exit("FAIL: Xvfb did not start")
    display = ":" + number
    runtime = tempfile.mkdtemp(prefix="ccwork-live-run-")
    # A check run from inside a ccwork terminal or a Claude session would
    # pass on CCWORK_CLAUDE_DEPTH (bin/claude then sends no ClaudeExited)
    # and the session's CLAUDE_CODE_* ids. The launched ccwork starts clean,
    # with the same Claude config folder.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CCWORK_", "CLAUDE")) or k == "CLAUDE_CONFIG_DIR"}
    env.update(DISPLAY=display, QT_QPA_PLATFORM="xcb", XDG_RUNTIME_DIR=runtime,
               DBUS_SESSION_BUS_ADDRESS="disabled:", **{CHILD_FLAG: "1", EVIDENCE_VAR: str(evidence)})
    env.pop("WAYLAND_DISPLAY", None)
    wm = subprocess.Popen(["openbox"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_until(lambda: subprocess.run(["wmctrl", "-m"], env=env, capture_output=True)
                          .returncode == 0, 5, step=0.1):
            sys.exit("FAIL: openbox did not start on " + display)
        print(f"display={display} runtime={runtime} evidence={evidence}", flush=True)
        with open(evidence / "output.txt", "w", buffering=1) as out:
            child = subprocess.Popen([sys.executable, *sys.argv], env=env, text=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            for line in child.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                out.write(line)
            rc = child.wait()
    finally:
        for p in (wm, xvfb):
            p.terminate()
            p.wait()
        shutil.rmtree(runtime, ignore_errors=True)
    sys.exit(rc)


def wait_until(predicate: Callable[[], bool], seconds: float, step: float = 0.2) -> bool:
    """Call `predicate` every `step` seconds until it holds, and give True.
    Give False when `seconds` pass first."""
    deadline = time.time() + seconds
    while not predicate():
        if time.time() > deadline:
            return False
        time.sleep(step)
    return True


def new_run_folder(parent: Path, name: str) -> Path:
    """A new folder `<parent>/<name>-<time>/`. The folders of the older runs
    of `name` are removed first."""
    for old in parent.glob(f"{name}-[0-9]*"):
        shutil.rmtree(old)
    folder = parent / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    folder.mkdir(parents=True)
    return folder


def evidence_dir() -> Path:
    """The run's folder in the repo, `tmp/live-runs/<check>-<time>/`: the
    check's output, the ccwork log and the screenshots."""
    return Path(os.environ[EVIDENCE_VAR])


def screenshot(name: str) -> None:
    """Save the whole display as `name` (a PNG) in the evidence folder."""
    subprocess.run(["import", "-window", "root", str(evidence_dir() / name)], check=True)


def new_sandbox(name: str) -> Path:
    """A new folder `tmp/wt-sandbox/<name>-<time>/`. A new path for each run
    keeps Claude Code's folder trust of an older run out of the check."""
    return new_run_folder(SANDBOXES, name)


def new_project(name: str, ignore: str = "") -> tuple[Path, Path]:
    """A new sandbox (`new_sandbox(name)`) and the git repo `proj` in it, on
    branch `main` with one commit of a README, and of a `.gitignore` with the
    `ignore` text when it is given."""
    sandbox = new_sandbox(name)
    files = {"README": "seed\n"} | ({".gitignore": ignore} if ignore else {})
    return sandbox, seed(sandbox / "proj", files)


def claude_worktrees(repo: Path) -> Path:
    """The folder where Claude Code makes the worktrees of `repo`."""
    return repo / ".claude" / "worktrees"


def key(*keys: str, pause: float = 0.5) -> None:
    """Press each xdotool key name in turn (`ctrl+shift+p`, `Return`), then
    give the app `pause` seconds to react."""
    subprocess.run(["xdotool", "key", "--delay", "80", *keys], check=True)
    time.sleep(pause)


def type_text(text: str) -> None:
    subprocess.run(["xdotool", "type", "--delay", "30", text], check=True)
    time.sleep(0.5)


def type_line(text: str) -> None:
    """Type `text`, then Enter. The pause before Enter keeps Claude Code from
    reading the text and the Enter as one paste."""
    type_text(text)
    key("Return")


def windows() -> str:
    """The `wmctrl -l` list: one line for each window, with its title."""
    return subprocess.run(["wmctrl", "-l"], capture_output=True, text=True).stdout


@contextmanager
def other_window(title: str) -> Iterator[None]:
    """A plain xterm with a known title, as "another app" to focus."""
    proc = subprocess.Popen(["xterm", "-T", title, "-e", "sleep", "600"])
    try:
        if not wait_until(lambda: title in windows(), 5, step=0.1):
            raise RuntimeError(f"window {title!r} did not appear")
        yield
    finally:
        proc.kill()


@dataclass
class Ccwork:
    """A ccwork that `ccwork()` launched, and its sandboxed config."""
    proc: subprocess.Popen
    config: Path  # its config folder: repos.json, settings.toml, open_sessions.json
    log_path: Path
    wid: str = ""

    def log(self) -> str:
        return self.log_path.read_text(errors="replace")

    def store(self) -> dict:
        """`repos.json`, or {} when the read meets ccwork's write."""
        try:
            return json.loads((self.config / "repos.json").read_text())
        except json.JSONDecodeError:
            return {}

    def row(self) -> dict:
        """The first row."""
        return (self.store().get("repos") or [{}])[0]

    def row_path(self) -> str:
        return self.row().get("path", "")

    def recent(self) -> list:
        """The `recent` list of `repos.json`; empty while ccwork has not
        written one."""
        return self.store().get("recent", [])

    def hook_events(self) -> list[str]:
        """The name of each hook event in the log, in order."""
        return [l.split("hook event=")[1].split()[0]
                for l in self.log().splitlines() if "hook event=" in l]

    def dispatches(self) -> int:
        """The count of shortcuts that the key grab has dispatched."""
        return self.log().count("KeyGrabFilter DISPATCH")

    def focus(self) -> None:
        subprocess.run(["wmctrl", "-ia", self.wid], check=True)
        time.sleep(0.8)

    def click(self, x: int, y: int, button: int = 1) -> None:
        """Click at (x, y) in the ccwork window."""
        subprocess.run(["xdotool", "mousemove", "--window", str(int(self.wid, 16)), str(x), str(y),
                        "click", str(button)], check=True)
        time.sleep(0.8)

    def open_terminal(self) -> None:
        """Open the first row's terminal (Ctrl+Shift+1), and wait for its shell."""
        key("ctrl+shift+1", pause=3.0)


@contextmanager
def ccwork(sandbox: Path, rows: Sequence[Path | dict] = (), settings: str = "") -> Iterator[Ccwork]:
    """Launch ccwork with its config in `<sandbox>/config` and `rows` in its
    `repos.json`: a path, or a row dict. A row with no `id` gets `row1`,
    `row2`, and so on. `settings` is the text of its `settings.toml`. ccwork logs to `ccwork.log` in the evidence folder.
    When the window shows, it is focused and yielded. At the end ccwork
    stops, and the worktrees that Claude Code made in each row's repo
    (`.claude/worktrees/`) are unlocked and removed: a session that dies
    keeps its lock."""
    xdg_config = sandbox / "config"
    config = xdg_config / "ccwork"
    entries = [{"id": f"row{i}", **(r if isinstance(r, dict) else {"path": str(r)})}
               for i, r in enumerate(rows, 1)]
    config.mkdir(parents=True)
    (config / "repos.json").write_text(json.dumps({"version": 1, "repos": entries}))
    if settings:
        (config / "settings.toml").write_text(settings)
    log_path = evidence_dir() / "ccwork.log"
    env = dict(os.environ, XDG_CONFIG_HOME=str(xdg_config), CCWORK_LOG="INFO")
    with open(log_path, "wb") as log:
        proc = subprocess.Popen([str(REPO / ".venv/bin/python"), "-m", "src.main"], cwd=str(REPO),
                                env=env, stdout=log, stderr=subprocess.STDOUT)
    print(f"pid={proc.pid} sandbox={sandbox}", flush=True)
    app = Ccwork(proc, config, log_path)
    try:
        def started() -> bool:
            # The window is found by WM_CLASS (`main.py.ccwork`). A title match is
            # not safe: a shell prompt in a title often holds "ccwork" as the cwd.
            out = subprocess.run(["wmctrl", "-lx"], capture_output=True, text=True).stdout
            app.wid = next((l.split()[0] for l in out.splitlines() if "main.py.ccwork" in l), "")
            return bool(app.wid) and "global keys:" in app.log()

        if not wait_until(started, STARTUP_S, step=0.1):
            raise RuntimeError(f"ccwork did not start within {STARTUP_S} s")
        app.focus()
        yield app
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        for repo in (Path(e["path"]) for e in entries):
            worktrees = claude_worktrees(repo)
            for wt in (worktrees.iterdir() if worktrees.is_dir() else ()):
                for step in (["unlock"], ["remove", "--force"]):
                    git("-C", str(repo), "worktree", *step, str(wt), check=False)


def watch_claude(app: Ccwork, worktree: str = "", tick: Callable[[], None] | None = None) -> list[str]:
    """Sample the first row's path until ccwork logs ClaudeExited. Saves
    `in-worktree.png` when the row reaches `worktree`, and calls `tick` at
    each sample. Prints the paths, the end state of the row and the hook
    events, and gives the paths in the order seen."""
    seen: list[str] = []

    def exited() -> bool:
        path = app.row_path()
        if path and (not seen or seen[-1] != path):
            seen.append(path)
            if path == worktree:
                time.sleep(1.0)  # repos.json is written before the repaint
                screenshot("in-worktree.png")
        if tick:
            tick()
        return "ClaudeExited" in app.hook_events()

    if not wait_until(exited, CLAUDE_TIMEOUT_S, step=0.05):
        raise RuntimeError(f"no ClaudeExited within {CLAUDE_TIMEOUT_S} s")
    time.sleep(1.0)
    print("paths seen:", seen)
    print("final:", {k: app.row().get(k) for k in ("path", "home")}, "recent:", app.recent())
    print("hook events:", app.hook_events())
    return seen


def loads_ccwork_claude_md(folder: Path) -> bool:
    """Whether a `CLAUDE` session in `folder` loads ccwork's CLAUDE.md, from
    the memory files that `/context` lists."""
    out = subprocess.run(["bash", "-c", f"{CLAUDE} -p /context"], cwd=folder, check=True,
                         capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_S).stdout
    memory = out.split("### Memory Files", 1)[1].split("###", 1)[0]
    return str(REPO / "CLAUDE.md") in memory


def check_follow(name: str, command: str) -> int:
    """Run one `claude` command in the row's terminal that puts the session
    in `.claude/worktrees/<name>`. Passes when the row was on that worktree
    while Claude ran, and is back on the repo with no `home` and an empty
    `recent` after exit, and when a `CLAUDE` session in the repo does not
    load ccwork's CLAUDE.md."""
    sandbox, proj = new_project(name)
    worktree = str(claude_worktrees(proj) / name)
    with ccwork(sandbox, [proj]) as app:
        app.open_terminal()
        type_line(command)
        seen = watch_claude(app, worktree)
        return report({
            "followed in": worktree in seen,
            "back home": app.row_path() == str(proj),
            "home cleared": app.row().get("home") == "",
            "recent empty": app.recent() == [],
            "no ccwork CLAUDE.md": not loads_ccwork_claude_md(proj),
        })


def report(checks: dict[str, bool]) -> int:
    """Print each check and the result. Gives the exit code: 0 when each
    check holds, else 2."""
    for k, v in checks.items():
        print(f"  {k}: {'OK' if v else 'FAIL'}")
    result = all(checks.values())
    print(f"\nresult: {'PASS' if result else 'FAIL'}")
    return 0 if result else 2
