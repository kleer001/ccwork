"""RepoListModel: line-3 status text, row titles, and title-file sync.

The title file lives under the autouse XDG_RUNTIME_DIR temp dir. Its two
lines are the row title and the last agreed (synced) title.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core.hook_server import (
    EVENT_SESSION_START,
    EVENT_USER_PROMPT_SUBMIT,
    row_title_path,
)
from src.core.repo_store import Repo, RepoStore
from src.ui.badge_theme import STATUS_ATTENTION, STATUS_LABELS
from src.ui.repo_model import ROLE_STATUS_TEXT, ROLE_TITLE, RepoListModel


def _model(tmp_path: Path, *repos: Repo) -> RepoListModel:
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = list(repos) or [Repo(path=str(tmp_path / "garden"))]
    return RepoListModel(store)


def _rid(model: RepoListModel) -> str:
    return model._store.repos[0].id


def _status_text(model: RepoListModel) -> str:
    return model.index(0).data(ROLE_STATUS_TEXT)


def _title_file(rid: str) -> list[str]:
    return row_title_path(rid).read_text().split("\n")[:2]


# ── ROLE_STATUS_TEXT ──


def test_status_text_is_the_badge_word(tmp_path: Path) -> None:
    model = _model(tmp_path)
    model.set_status(_rid(model), STATUS_ATTENTION)
    assert _status_text(model) == STATUS_LABELS[STATUS_ATTENTION]


def test_status_text_badge_wins_over_working(tmp_path: Path) -> None:
    model = _model(tmp_path)
    rid = _rid(model)
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, rid)
    model.set_status(rid, STATUS_ATTENTION, word="Rate limited")
    assert _status_text(model) == "Rate limited"


def test_status_text_working_shows_elapsed_minutes(tmp_path: Path) -> None:
    model = _model(tmp_path)
    rid = _rid(model)
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, rid)
    assert _status_text(model) == "Working · 0s"

    model._turn_started[rid] -= 130
    assert _status_text(model) == "Working · 2m"


def test_status_text_claude_open_when_terminal_and_session_active(tmp_path: Path) -> None:
    model = _model(tmp_path)
    rid = _rid(model)
    model.set_terminal_active(rid, True)
    model.apply_hook_event(EVENT_SESSION_START, rid)
    assert _status_text(model) == "Claude open"


def test_status_text_empty_for_bare_shell(tmp_path: Path) -> None:
    model = _model(tmp_path)
    model.set_terminal_active(_rid(model), True)
    assert _status_text(model) == ""


def test_status_text_empty_without_terminal_or_session(tmp_path: Path) -> None:
    model = _model(tmp_path)
    assert _status_text(model) == ""


def test_status_text_compacting(tmp_path: Path) -> None:
    model = _model(tmp_path)
    model.set_compacting(_rid(model), True)
    assert _status_text(model) == "Compacting"


# ── set_title ──


def test_set_title_writes_file_with_previous_title_as_synced(tmp_path: Path) -> None:
    model = _model(tmp_path)
    rid = _rid(model)
    model.set_title(rid, "fix login bug")
    assert _title_file(rid) == ["fix login bug", ""]

    # The session never agreed on "fix login bug", so the synced title stays
    # "" and the sink still pushes the new title to Claude.
    model.set_title(rid, "second task")
    assert _title_file(rid) == ["second task", ""]


def test_set_title_keeps_the_agreed_title_as_synced(tmp_path: Path) -> None:
    model = _model(tmp_path, Repo(path=str(tmp_path / "garden"), title="agreed"))
    rid = _rid(model)
    model.sync_session_title(rid, "agreed")

    model.set_title(rid, "next")

    assert _title_file(rid) == ["next", "agreed"]


def test_set_title_normalises_whitespace_and_saves(tmp_path: Path) -> None:
    model = _model(tmp_path)
    rid = _rid(model)
    model.set_title(rid, "  fix   login\tbug ")
    assert model._store.find_by_id(rid).title == "fix login bug"
    assert model.index(0).data(ROLE_TITLE) == "fix login bug"

    reloaded = RepoStore(config_path=tmp_path / "repos.json")
    reloaded.load()
    assert reloaded.repos[0].title == "fix login bug"


def test_set_title_empty_clears_the_row_title(tmp_path: Path) -> None:
    model = _model(tmp_path)
    rid = _rid(model)
    model.set_title(rid, "fix login bug")
    model.set_title(rid, "")
    assert model._store.find_by_id(rid).title == ""
    assert _title_file(rid) == ["", ""]


def test_set_title_unknown_row_is_a_no_op(tmp_path: Path) -> None:
    model = _model(tmp_path)
    model.set_title("no-such-row", "anything")
    assert not row_title_path("no-such-row").exists()


# ── sync_session_title ──


def test_session_rename_is_adopted_when_row_is_in_sync(tmp_path: Path) -> None:
    model = _model(tmp_path, Repo(path=str(tmp_path / "garden"), title="old"))
    rid = _rid(model)

    model.sync_session_title(rid, "renamed in claude")

    assert model._store.find_by_id(rid).title == "renamed in claude"
    assert _title_file(rid) == ["renamed in claude", "renamed in claude"]


def test_row_title_is_kept_when_row_changed_since_last_sync(tmp_path: Path) -> None:
    model = _model(tmp_path, Repo(path=str(tmp_path / "garden"), title="old"))
    rid = _rid(model)
    model.set_title(rid, "mine")

    model.sync_session_title(rid, "old")

    assert model._store.find_by_id(rid).title == "mine"
    assert model._title_synced[rid] == "mine"
    assert _title_file(rid) == ["mine", "mine"]


def test_missing_session_title_never_clears_row_title(tmp_path: Path) -> None:
    model = _model(tmp_path, Repo(path=str(tmp_path / "garden"), title="keep me"))
    rid = _rid(model)

    model.sync_session_title(rid, None)
    model.sync_session_title(rid, "")

    assert model._store.find_by_id(rid).title == "keep me"


def test_sync_for_unknown_row_is_a_no_op(tmp_path: Path) -> None:
    model = _model(tmp_path)
    model.sync_session_title("no-such-row", "renamed")
    assert not row_title_path("no-such-row").exists()


# ── publish_titles ──


def test_publish_titles_writes_every_row(tmp_path: Path) -> None:
    model = _model(
        tmp_path,
        Repo(path=str(tmp_path / "a"), title="first"),
        Repo(path=str(tmp_path / "b")),
    )
    ids = [r.id for r in model._store.repos]

    model.publish_titles()

    assert _title_file(ids[0]) == ["first", "first"]
    assert _title_file(ids[1]) == ["", ""]


def test_removing_a_row_deletes_its_title_file(qapp, tmp_path) -> None:
    from src.core.hook_server import row_title_path
    from src.core.repo_store import Repo, RepoStore
    from src.ui.repo_model import RepoListModel

    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path="/a", title="t")]
    model = RepoListModel(store)
    model.publish_titles()
    path = row_title_path(store.repos[0].id)
    assert path.exists()
    model.remove_repo_at(0)
    assert not path.exists()
