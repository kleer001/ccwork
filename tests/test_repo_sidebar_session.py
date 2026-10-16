"""Coverage for the session-active flag and its cascade-clear on SessionEnd.

The ambient ⠿ badge and membership in the floated "active" group both ride
a single per-row boolean: `_session_active`, keyed by repo id. SessionStart flips it on;
SessionEnd flips it off, cascade-clears the per-session signals (`_status`,
`_working`, `_subagents`, `_turn_started`), and sinks the row to the bottom
of the sort so a finished session stops reading as pending work.
"""

from __future__ import annotations

from pathlib import Path

from src.core.hook_server import (
    EVENT_NOTIFICATION,
    EVENT_SESSION_END,
    EVENT_SESSION_START,
    EVENT_STOP,
    EVENT_SUBAGENT_START,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore
from src.ui.repo_sidebar import (
    ROLE_ACTIVE_GROUP,
    ROLE_SUBAGENTS,
    ROLE_SESSION_ACTIVE,
    ROLE_STATUS,
    ROLE_WORKING,
    RepoListModel,
    STATUS_ATTENTION,
    STATUS_DONE,
)


def _store_with(repo_path: str, cfg_path: Path) -> RepoStore:
    store = RepoStore(config_path=cfg_path)
    store.repos = [Repo(path=repo_path)]
    return store


def test_session_start_sets_active(qapp, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    assert model.index(0).data(ROLE_SESSION_ACTIVE) is False
    model.apply_hook_event(EVENT_SESSION_START, rid)
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is True
    assert model.is_session_active(rid) is True


def test_session_end_clears_active_and_status(qapp, tmp_path: Path) -> None:
    """Exiting Claude makes any leftover DONE/ATTENTION dot stale —
    cascade-clear so the row reads as idle."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_SESSION_START, rid)
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, rid)
    model.apply_hook_event(EVENT_STOP, rid)
    assert model.index(0).data(ROLE_STATUS) == STATUS_DONE

    model.apply_hook_event(EVENT_SESSION_END, rid)
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is False
    assert model.index(0).data(ROLE_STATUS) == ""
    assert model.index(0).data(ROLE_WORKING) is False


def test_session_end_clears_stuck_working(qapp, tmp_path: Path) -> None:
    """If a session is killed mid-turn, the working flag is stuck True
    without a Stop. SessionEnd must clear it so the spinner stops."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_SESSION_START, rid)
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, rid)
    assert model.index(0).data(ROLE_WORKING) is True

    model.apply_hook_event(EVENT_SESSION_END, rid)
    assert model.index(0).data(ROLE_WORKING) is False
    assert model.any_working() is False


def test_session_end_clears_subagents(qapp, tmp_path: Path) -> None:
    """Subagents don't outlive their parent session — clear the live set
    on SessionEnd so the indicator stops, and a late SubagentStop for one
    of those ids finds nothing to remove."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_SESSION_START, rid)
    model.apply_hook_event(EVENT_SUBAGENT_START, rid, {"agent_id": "a1"})
    model.apply_hook_event(EVENT_SUBAGENT_START, rid, {"agent_id": "a2"})
    assert model.subagents(rid) == 2

    model.apply_hook_event(EVENT_SESSION_END, rid)
    assert model.subagents(rid) == 0
    assert model.index(0).data(ROLE_SUBAGENTS) == 0
    assert model.any_subagents() is False


def test_session_end_clears_attention(qapp, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_SESSION_START, rid)
    model.apply_hook_event(EVENT_NOTIFICATION, rid, {"notification_type": "permission_prompt"})
    assert model.index(0).data(ROLE_STATUS) == STATUS_ATTENTION

    model.apply_hook_event(EVENT_SESSION_END, rid)
    assert model.index(0).data(ROLE_STATUS) == ""


def test_clear_session_tears_down_on_exit(qapp, tmp_path: Path) -> None:
    """`/exit` gets no SessionEnd hook (anthropics/claude-code#17885), so
    the terminal-process exit calls clear_session directly. It must match
    the SessionEnd cascade: a stuck working spinner and a leaked subagent
    twinkle both clear, so nothing animates forever after `/exit`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_SESSION_START, rid)
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, rid)
    model.apply_hook_event(EVENT_SUBAGENT_START, rid, {"agent_id": "a1"})
    assert model.any_working() is True
    assert model.any_subagents() is True

    model.clear_session(rid)
    assert model.any_working() is False
    assert model.any_subagents() is False
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is False


def test_relaunch_clears_x_indicator(qapp, tmp_path: Path) -> None:
    """User exits Claude (⠿ goes dark), then types `claude` again. The next
    SessionStart must flip session_active back to True so the ⠿ returns."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_SESSION_START, rid)
    model.apply_hook_event(EVENT_SESSION_END, rid)
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is False

    model.apply_hook_event(EVENT_SESSION_START, rid)
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is True


def test_sibling_session_end_keeps_active_session_working(qapp, tmp_path: Path) -> None:
    """Two `claude` sessions run in one row's terminal. One is mid-turn
    (working spinner up); the other exits. The dead session's SessionEnd
    must NOT cascade-clear the live session's working flag — the bug where
    an active row lost its spinner mid-turn."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    live = {"session_id": "live-aaa"}
    other = {"session_id": "other-bbb"}
    model.apply_hook_event(EVENT_SESSION_START, rid, live)
    model.apply_hook_event(EVENT_SESSION_START, rid, other)
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, rid)
    assert model.index(0).data(ROLE_WORKING) is True

    # The idle sibling exits. The working session keeps spinning.
    model.apply_hook_event(EVENT_SESSION_END, rid, other)
    assert model.index(0).data(ROLE_WORKING) is True
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is True

    # When the last session ends, the cascade runs as before.
    model.apply_hook_event(EVENT_SESSION_END, rid, live)
    assert model.index(0).data(ROLE_WORKING) is False
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is False


def test_unknown_session_end_still_cascades(qapp, tmp_path: Path) -> None:
    """A SessionEnd whose id we never tracked, with no other live session on
    the path, must still tear down (matches the pre-tracking behavior so a
    resumed session whose SessionStart we missed doesn't get stuck)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, rid)
    assert model.index(0).data(ROLE_WORKING) is True
    model.apply_hook_event(EVENT_SESSION_END, rid, {"session_id": "ghost"})
    assert model.index(0).data(ROLE_WORKING) is False


def test_session_active_is_per_row_on_duplicate_paths(qapp, tmp_path: Path) -> None:
    """Two duplicate rows on one path keep independent session state. A
    session in one row must not light the other row's ⠿ badge."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path=str(repo)), Repo(path=str(repo))]
    model = RepoListModel(store)
    first, second = _ids(model)

    model.apply_hook_event(EVENT_SESSION_START, first, {"session_id": "s1"})
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is True
    assert model.index(1).data(ROLE_SESSION_ACTIVE) is False

    model.apply_hook_event(EVENT_SESSION_END, first, {"session_id": "s1"})
    model.apply_hook_event(EVENT_SESSION_START, second, {"session_id": "s2"})
    assert model.is_session_active(first) is False
    assert model.is_session_active(second) is True


def _three_repos(tmp_path: Path) -> RepoListModel:
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path="/a"), Repo(path="/b"), Repo(path="/c")]
    return RepoListModel(store)


def _ids(model: RepoListModel) -> list[str]:
    return [r.id for r in model._store.repos]


def test_session_end_sinks_row_to_the_bottom(qapp, tmp_path: Path) -> None:
    """Quitting Claude drops the repo below every other row, including ones
    that never ran anything — a finished session is not pending work."""
    model = _three_repos(tmp_path)
    a, _b, _c = _ids(model)
    model.apply_hook_event(EVENT_SESSION_START, a, {"session_id": "s1"})
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, a)
    model.apply_hook_event(EVENT_STOP, a)

    model.apply_auto_arrange()
    assert [r.path for r in model._store.repos] == ["/a", "/b", "/c"]

    model.apply_hook_event(EVENT_SESSION_END, a, {"session_id": "s1"})
    model.apply_auto_arrange()
    assert [r.path for r in model._store.repos] == ["/b", "/c", "/a"]


def test_newest_exit_sinks_below_an_earlier_one(qapp, tmp_path: Path) -> None:
    model = _three_repos(tmp_path)
    a, b, _c = _ids(model)
    for rid, sid in ((a, "s1"), (b, "s2")):
        model.apply_hook_event(EVENT_SESSION_START, rid, {"session_id": sid})
        model.apply_hook_event(EVENT_SESSION_END, rid, {"session_id": sid})

    model.apply_auto_arrange()
    assert [r.path for r in model._store.repos] == ["/c", "/a", "/b"]


def test_new_activity_lifts_a_sunk_row(qapp, tmp_path: Path) -> None:
    """Coming back to a repo puts it back on the recency axis."""
    model = _three_repos(tmp_path)
    a, _b, _c = _ids(model)
    model.apply_hook_event(EVENT_SESSION_START, a, {"session_id": "s1"})
    model.apply_hook_event(EVENT_SESSION_END, a, {"session_id": "s1"})
    model.apply_auto_arrange()
    assert model._store.repos[-1].path == "/a"

    model.apply_hook_event(EVENT_SESSION_START, a, {"session_id": "s2"})
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, a)
    model.apply_auto_arrange()
    assert model._store.repos[0].path == "/a"


def test_bare_terminal_is_not_in_the_active_group(qapp, tmp_path: Path) -> None:
    """A terminal left at a bash prompt must not hold a floated top slot."""
    model = _three_repos(tmp_path)
    ids = _ids(model)
    model.set_terminal_active(ids[2], True)

    assert model.index(2).data(ROLE_ACTIVE_GROUP) is False
    assert model.apply_terminal_grouping() is False

    model.apply_hook_event(EVENT_SESSION_START, ids[2], {"session_id": "s1"})
    assert model.index(2).data(ROLE_ACTIVE_GROUP) is True
    assert model.apply_terminal_grouping() is True
    assert [r.path for r in model._store.repos] == ["/c", "/a", "/b"]
