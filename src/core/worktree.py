"""Make and remove linked git worktrees for sidebar rows
(docs/specs/worktree.md 5 and 7).

`worktree_source` reads the source row's repository once; `worktree_plan`
checks a branch name against it; `make_worktree` runs the git commands.
`ignored_entries` and `has_submodules` feed the remove dialog, and
`remove_worktree` deletes the folder and its branch. Each git failure
raises `GitError` with git's own message.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.core.repo_store import current_branch, git_common_dir, main_name

# Upper bound for one git command (a worktree checkout is the slowest).
GIT_TIMEOUT_S = 30

UNMERGED_NOTE = ("The folder is deleted. The branch {branch} stays, because it has "
                 "commits that are not merged.")
BRANCH_KEPT_NOTE = "The folder is deleted. The branch {branch} stays: {reason}"


class GitError(RuntimeError):
    """A git command failed. The message is git's own stderr."""


def _run(path: str, *args: str) -> subprocess.CompletedProcess:
    """Run `git -C path args` in the C locale, so the messages that ccwork
    reads are stable. Raises GitError when git does not finish in time."""
    try:
        return subprocess.run(["git", "-C", path, *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT_S, env={**os.environ, "LC_ALL": "C"})
    except subprocess.TimeoutExpired:
        raise GitError(f"git {args[0]} did not finish in {GIT_TIMEOUT_S} s") from None


def _git(path: str, *args: str) -> str:
    """stdout of `git -C path args`; GitError with git's stderr on failure."""
    r = _run(path, *args)
    if r.returncode != 0:
        raise GitError(r.stderr.strip() or f"git {args[0]} exited {r.returncode}")
    return r.stdout.strip()


def _git_ok(path: str, *args: str) -> bool:
    """True when `git -C path args` exits 0."""
    return _run(path, *args).returncode == 0


@dataclass(frozen=True)
class WorktreeSource:
    """What "Make worktree…" reads once from the source row's folder."""
    path: str
    main_name: str
    parent: str          # the folder that holds the main checkout
    base: str | None     # the source branch; None on a detached HEAD
    commit: str          # short hash of the source HEAD
    dirty: bool          # uncommitted changes stay in the source (F7)


@dataclass(frozen=True)
class WorktreePlan:
    source: WorktreeSource
    name: str
    folder: str
    problem: str         # why OK stays off; "" when the plan can run


def main_checkout(common: str) -> Path:
    """The main checkout folder from the common dir: `<main>` for
    `<main>/.git`, the common dir itself for a bare repository."""
    return Path(common).parent if Path(common).name == ".git" else Path(common)


def worktree_source(path: str) -> WorktreeSource:
    """Read the source row's repository state. Raises GitError outside git."""
    common = git_common_dir(path)
    if common is None:
        raise GitError(f"{path} is not in a git repository")
    return WorktreeSource(
        path=path,
        main_name=main_name(Path(common)),
        parent=str(main_checkout(common).parent),
        base=current_branch(path),
        commit=_git(path, "rev-parse", "--short", "HEAD"),
        dirty=bool(_git(path, "status", "--porcelain")),
    )


def worktree_plan(src: WorktreeSource, name: str) -> WorktreePlan:
    """The folder for branch `name`, `<parent>/<main name>-<name>` with each
    `/` as `-`, and the first reason the plan cannot run."""
    folder = os.path.join(src.parent, f"{src.main_name}-{name.replace('/', '-')}")
    if not name:
        problem = "Type a name for the branch."
    elif not _git_ok(src.path, "check-ref-format", f"refs/heads/{name}"):
        problem = "Git does not accept this branch name."
    elif _git_ok(src.path, "show-ref", "--verify", "--quiet", f"refs/heads/{name}"):
        problem = f"The branch {name} exists."
    elif os.path.lexists(folder):
        problem = f"The folder {folder} exists."
    else:
        problem = ""
    return WorktreePlan(source=src, name=name, folder=folder, problem=problem)


def make_worktree(plan: WorktreePlan) -> str:
    """`git worktree add -b <name> <folder> HEAD` from the source, then
    record the source branch as `branch.<name>.ccworkBase` for the merge
    back. Returns the folder. Raises GitError with git's message."""
    _git(plan.source.path, "worktree", "add", "-b", plan.name, plan.folder, "HEAD")
    if plan.source.base:
        _git(plan.folder, "config", f"branch.{plan.name}.ccworkBase", plan.source.base)
    return plan.folder


def git_dir(folder: str) -> str:
    """The private git dir of `folder`: `<common dir>/worktrees/<name>` for
    a linked worktree."""
    return _git(folder, "rev-parse", "--absolute-git-dir")


def ignored_entries(folder: str) -> list[str]:
    """Ignored files of `folder`, and each wholly ignored folder as one entry
    that ends in `/`: what `git worktree remove` deletes with no question."""
    out = _git(folder, "ls-files", "-z", "--others", "--ignored", "--exclude-standard",
               "--directory")
    return [e for e in out.split("\0") if e]


def has_submodules(folder: str) -> bool:
    """True when the index of `folder` has a submodule entry (mode 160000).
    `git worktree remove` refuses such a worktree."""
    return any(line.startswith("160000 ")
               for line in _git(folder, "ls-files", "--stage").splitlines())


def remove_worktree(folder: str, branch: str) -> str:
    """`git worktree remove <folder>` (refuses changed or untracked files),
    then `git branch -d <branch>` (refuses unmerged commits) from the main
    checkout. Raises GitError when git refuses the folder. Once the folder
    is gone, a branch refusal does not raise: it returns a note for the user,
    else "" (docs/specs/worktree.md 7)."""
    common = git_common_dir(folder)
    if common is None:
        raise GitError(f"{folder} is not in a git repository")
    main = str(main_checkout(common))
    _git(main, "worktree", "remove", folder)
    if not branch:
        return ""
    r = _run(main, "branch", "-d", branch)
    if r.returncode == 0:
        return ""
    if "not fully merged" in r.stderr:
        return UNMERGED_NOTE.format(branch=branch)
    return BRANCH_KEPT_NOTE.format(branch=branch, reason=r.stderr.strip())
