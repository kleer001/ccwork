"""Tests for repo_store — persistence + branch lookup."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from src.core import repo_store
from src.core.repo_store import Repo, RepoStore


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "repos.json"


def test_load_empty_when_missing(store_path: Path) -> None:
    s = RepoStore(config_path=store_path)
    s.load()
    assert s.repos == []


def test_save_creates_parent_dir(tmp_path: Path) -> None:
    p = tmp_path / "a" / "b" / "repos.json"
    s = RepoStore(config_path=p)
    s.add("/tmp/x")
    s.save()
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["version"] == 1
    assert len(data["repos"]) == 1


def test_round_trip(store_path: Path, tmp_path: Path) -> None:
    r1 = tmp_path / "r1"
    r2 = tmp_path / "r2"
    r1.mkdir()
    r2.mkdir()
    s = RepoStore(config_path=store_path)
    assert s.add(str(r1)) is True
    assert s.add(str(r2)) is True
    s.save()

    s2 = RepoStore(config_path=store_path)
    s2.load()
    assert len(s2.repos) == 2
    assert s2.repos[0].path == str(r1)
    assert s2.repos[1].path == str(r2)


def test_add_deduplicates_by_realpath(store_path: Path, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)

    s = RepoStore(config_path=store_path)
    assert s.add(str(target)) is True
    assert s.add(str(link)) is False
    assert s.add(str(target) + "/") is False
    assert len(s.repos) == 1


def test_remove(store_path: Path, tmp_path: Path) -> None:
    r1 = tmp_path / "r1"
    r1.mkdir()
    s = RepoStore(config_path=store_path)
    s.add(str(r1))
    assert s.remove(str(r1)) is True
    assert s.remove(str(r1)) is False
    assert s.repos == []


def test_move_reorders(store_path: Path, tmp_path: Path) -> None:
    paths = [tmp_path / f"r{i}" for i in range(3)]
    for p in paths:
        p.mkdir()
    s = RepoStore(config_path=store_path)
    for p in paths:
        s.add(str(p))
    # move r0 to position 2 (end)
    assert s.move(str(paths[0]), 2) is True
    assert [r.path for r in s.repos] == [str(paths[1]), str(paths[2]), str(paths[0])]


def test_move_unknown_path_returns_false(store_path: Path) -> None:
    s = RepoStore(config_path=store_path)
    assert s.move("/does/not/exist", 0) is False


def test_repo_name_from_path() -> None:
    assert Repo(path="/home/user/myrepo").name == "myrepo"
    assert Repo(path="/home/user/myrepo/").name == "myrepo"
    assert Repo(path="/").name == "/"


def test_load_tolerates_empty_file(store_path: Path) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text("")
    s = RepoStore(config_path=store_path)
    s.load()
    assert s.repos == []


def test_load_rejects_non_object(store_path: Path) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text("[]")
    s = RepoStore(config_path=store_path)
    with pytest.raises(ValueError):
        s.load()


def test_load_tolerates_corrupt_json(store_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A half-written repos.json should not crash the app — treat as empty."""
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text("{\"repos\":[{\"path\":\"/x\"},")  # truncated
    s = RepoStore(config_path=store_path)
    import logging
    with caplog.at_level(logging.WARNING):
        s.load()
    assert s.repos == []
    assert any("not valid JSON" in r.message for r in caplog.records)


def test_load_skips_malformed_repo_entries(store_path: Path) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps({"version": 1, "repos": [
        {"path": "/ok"},
        "not-an-object",
        {"no_path_key": True},
        {"path": "/ok2"},
    ]}))
    s = RepoStore(config_path=store_path)
    s.load()
    assert [r.path for r in s.repos] == ["/ok", "/ok2"]


def test_default_config_path_respects_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert repo_store.default_config_path() == tmp_path / "ccwork" / "repos.json"


def test_default_config_path_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert repo_store.default_config_path() == Path.home() / ".config" / "ccwork" / "repos.json"


# ── git helpers ──────────────────────────────────────────────────────────────


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "f").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True)
    return tmp_path


def test_is_git_root_true(git_repo: Path) -> None:
    assert repo_store.is_git_root(git_repo) is True


def test_is_git_root_false_for_subdir(git_repo: Path) -> None:
    sub = git_repo / "sub"
    sub.mkdir()
    assert repo_store.is_git_root(sub) is False


def test_is_git_root_false_for_non_repo(tmp_path: Path) -> None:
    (tmp_path / "not_a_repo").mkdir()
    assert repo_store.is_git_root(tmp_path / "not_a_repo") is False


def test_current_branch(git_repo: Path) -> None:
    assert repo_store.current_branch(git_repo) == "main"


def test_current_branch_detached(git_repo: Path) -> None:
    sha = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(git_repo), "checkout", "-q", sha], check=True)
    assert repo_store.current_branch(git_repo) is None


def test_current_branch_non_repo(tmp_path: Path) -> None:
    assert repo_store.current_branch(tmp_path) is None
