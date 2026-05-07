"""Tests for repo_store — persistence + branch lookup."""

from __future__ import annotations

import json
import os
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
    # New schema fields persisted
    assert "id" in data["repos"][0]
    assert "instance" in data["repos"][0]


def test_round_trip(store_path: Path, tmp_path: Path) -> None:
    r1 = tmp_path / "r1"
    r2 = tmp_path / "r2"
    r1.mkdir()
    r2.mkdir()
    s = RepoStore(config_path=store_path)
    a = s.add(str(r1))
    b = s.add(str(r2))
    s.save()

    s2 = RepoStore(config_path=store_path)
    s2.load()
    assert len(s2.repos) == 2
    assert s2.repos[0].path == str(r1)
    assert s2.repos[1].path == str(r2)
    # Ids round-trip identically.
    assert s2.repos[0].id == a.id
    assert s2.repos[1].id == b.id


def test_add_allows_duplicates_with_roman_suffixes(store_path: Path, tmp_path: Path) -> None:
    """Adding the same path twice promotes the first to instance=1 and the
    second to instance=2 — sequence restarts each time we re-enter the
    duplicate state."""
    target = tmp_path / "target"
    target.mkdir()

    s = RepoStore(config_path=store_path)
    a = s.add(str(target))
    assert a.instance == 0
    assert a.display_name == "target"

    b = s.add(str(target))
    # 1→2 promotes the original to (I).
    assert s.repos[0].instance == 1
    assert b.instance == 2
    assert s.repos[0].display_name == "target (I)"
    assert b.display_name == "target (II)"
    assert len(s.repos) == 2


def test_add_third_duplicate_appends(store_path: Path, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    s = RepoStore(config_path=store_path)
    s.add(str(target)); s.add(str(target))
    c = s.add(str(target))
    assert [r.instance for r in s.repos] == [1, 2, 3]
    assert c.display_name == "target (III)"


def test_remove_middle_keeps_gaps(store_path: Path, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    s = RepoStore(config_path=store_path)
    a = s.add(str(target)); b = s.add(str(target)); c = s.add(str(target))
    assert s.remove_by_id(b.id) is True
    # Gap preserved while count stays >=2.
    assert [r.instance for r in s.repos] == [1, 3]
    assert s.repos[0].id == a.id
    assert s.repos[1].id == c.id


def test_remove_drops_suffix_when_one_left(store_path: Path, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    s = RepoStore(config_path=store_path)
    a = s.add(str(target)); b = s.add(str(target))
    assert s.remove_by_id(b.id) is True
    # Survivor's suffix disappears.
    assert s.repos[0].instance == 0
    assert s.repos[0].display_name == "target"
    assert s.repos[0].id == a.id


def test_re_add_restarts_sequence(store_path: Path, tmp_path: Path) -> None:
    """After the count drops to 1 (suffix cleared), a fresh duplicate add
    promotes the survivor back to (I) — numbering restarts."""
    target = tmp_path / "target"
    target.mkdir()
    s = RepoStore(config_path=store_path)
    a = s.add(str(target)); b = s.add(str(target))   # I, II
    s.remove_by_id(b.id)                              # back to bare name
    s.add(str(target))                                # re-enter duplicates
    assert [r.instance for r in s.repos] == [1, 2]
    assert s.repos[0].id == a.id


def test_add_normalizes_symlinks(store_path: Path, tmp_path: Path) -> None:
    """Realpath normalization still applies — adding via a symlink stores
    the resolved path so duplicate detection treats both as the same repo."""
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)

    s = RepoStore(config_path=store_path)
    s.add(str(target))
    s.add(str(link))
    assert len(s.repos) == 2
    assert s.repos[0].instance == 1
    assert s.repos[1].instance == 2
    # Both stored as the same realpath.
    assert s.repos[0].path == str(target)
    assert s.repos[1].path == str(target)


def test_remove_by_id_missing_returns_false(store_path: Path) -> None:
    s = RepoStore(config_path=store_path)
    assert s.remove_by_id("no-such-id") is False


def test_move_by_id_reorders(store_path: Path, tmp_path: Path) -> None:
    paths = [tmp_path / f"r{i}" for i in range(3)]
    for p in paths:
        p.mkdir()
    s = RepoStore(config_path=store_path)
    added = [s.add(str(p)) for p in paths]
    assert s.move_by_id(added[0].id, 2) is True
    assert [r.path for r in s.repos] == [str(paths[1]), str(paths[2]), str(paths[0])]


def test_move_by_id_unknown_returns_false(store_path: Path) -> None:
    s = RepoStore(config_path=store_path)
    assert s.move_by_id("nope", 0) is False


def test_repos_for_path_finds_all_duplicates(store_path: Path, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    s = RepoStore(config_path=store_path)
    s.add(str(target)); s.add(str(target)); s.add(str(target))
    assert len(s.repos_for_path(str(target))) == 3


def test_repo_name_and_display_name() -> None:
    assert Repo(path="/home/user/myrepo").name == "myrepo"
    assert Repo(path="/home/user/myrepo/").name == "myrepo"
    assert Repo(path="/").name == "/"
    # display_name == name when instance is 0.
    assert Repo(path="/x/y").display_name == "y"
    assert Repo(path="/x/y", instance=1).display_name == "y (I)"
    assert Repo(path="/x/y", instance=4).display_name == "y (IV)"
    assert Repo(path="/x/y", instance=39).display_name == "y (XXXIX)"


def test_emoji_in_display_name() -> None:
    """Optional leading emoji prefixes the basename and survives the suffix."""
    assert Repo(path="/x/y", emoji="🐛").display_name == "🐛 y"
    assert Repo(path="/x/y", emoji="🐛", instance=2).display_name == "🐛 y (II)"
    assert Repo(path="/x/y", emoji="").display_name == "y"


def test_emoji_round_trip(store_path: Path, tmp_path: Path) -> None:
    target = tmp_path / "r"
    target.mkdir()
    s = RepoStore(config_path=store_path)
    r = s.add(str(target))
    r.emoji = "🚀"
    s.save()

    s2 = RepoStore(config_path=store_path)
    s2.load()
    assert s2.repos[0].emoji == "🚀"


def test_load_back_compat_missing_emoji(store_path: Path) -> None:
    """Older repos.json without an `emoji` key loads with empty string."""
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps({
        "version": 1,
        "repos": [{"path": "/some/repo", "id": "abc", "instance": 0}],
    }))
    s = RepoStore(config_path=store_path)
    s.load()
    assert s.repos[0].emoji == ""


def test_to_roman_basic() -> None:
    from src.core.repo_store import to_roman
    assert to_roman(1) == "I"
    assert to_roman(4) == "IV"
    assert to_roman(9) == "IX"
    assert to_roman(40) == "XL"
    assert to_roman(90) == "XC"
    assert to_roman(400) == "CD"
    assert to_roman(900) == "CM"
    assert to_roman(1994) == "MCMXCIV"
    assert to_roman(3999) == "MMMCMXCIX"


def test_to_roman_out_of_range_raises() -> None:
    from src.core.repo_store import to_roman
    with pytest.raises(ValueError):
        to_roman(0)
    with pytest.raises(ValueError):
        to_roman(4000)
    with pytest.raises(ValueError):
        to_roman(-1)


def test_load_back_compat_missing_id_and_instance(store_path: Path) -> None:
    """Old repos.json files (no id/instance) still load — fields are filled in."""
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps({
        "version": 1,
        "repos": [{"path": "/some/repo"}],
    }))
    s = RepoStore(config_path=store_path)
    s.load()
    assert len(s.repos) == 1
    assert s.repos[0].path == "/some/repo"
    assert s.repos[0].id  # fresh uuid
    assert s.repos[0].instance == 0


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
