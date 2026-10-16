"""Coverage for the live-subagent set and its left-edge twinkle indicator.

SubagentStart adds the event's `agent_id` to the row's set; SubagentStop
removes the same id. While the set is non-empty, the delegate paints the
SUBAGENT_FRAMES twinkle (·→✦→✶→❋→✶→✦) on the LEFT edge of the row, alongside
whatever the right-edge column is showing — working spinner during the main
turn, green DONE dot after Stop, etc.

Foreground and background subagents both count; the indicators are
visually separate so the user can tell parallel work is in flight.
"""

from __future__ import annotations

from pathlib import Path

from src.core.hook_server import (
    EVENT_NOTIFICATION,
    EVENT_STOP,
    EVENT_SUBAGENT_START,
    EVENT_SUBAGENT_STOP,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore
from src.ui.repo_sidebar import (
    ROLE_STATUS,
    ROLE_SUBAGENTS,
    ROLE_WORKING,
    RepoListModel,
    STATUS_ATTENTION,
    STATUS_DONE,
)


def _store_with(repo_path: str, cfg_path: Path) -> RepoStore:
    store = RepoStore(config_path=cfg_path)
    store.repos = [Repo(path=repo_path)]
    return store


def _agent(agent_id: str) -> dict:
    return {"agent_id": agent_id, "agent_type": "general-purpose"}


def test_subagent_start_adds_one_subagent(qapp, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_SUBAGENT_START, rid, _agent("a1"))

    assert model.index(0).data(ROLE_SUBAGENTS) == 1
    assert model.subagents(rid) == 1


def test_repeated_subagent_start_counts_once(qapp, tmp_path: Path) -> None:
    """A resumed subagent fires SubagentStart again with the same agent_id;
    the set absorbs the repeat."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_SUBAGENT_START, rid, _agent("a1"))
    model.apply_hook_event(EVENT_SUBAGENT_START, rid, _agent("a1"))
    assert model.subagents(rid) == 1

    model.apply_hook_event(EVENT_SUBAGENT_START, rid, _agent("a2"))
    assert model.subagents(rid) == 2


def test_subagent_stop_removes_its_own_id(qapp, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_SUBAGENT_START, rid, _agent("a1"))
    model.apply_hook_event(EVENT_SUBAGENT_START, rid, _agent("a2"))
    assert model.subagents(rid) == 2

    model.apply_hook_event(EVENT_SUBAGENT_STOP, rid, _agent("a1"))
    assert model.subagents(rid) == 1
    assert model.index(0).data(ROLE_SUBAGENTS) == 1

    model.apply_hook_event(EVENT_SUBAGENT_STOP, rid, _agent("a2"))
    assert model.subagents(rid) == 0
    assert model.index(0).data(ROLE_SUBAGENTS) == 0


def test_subagent_stop_of_unknown_id_is_noop(qapp, tmp_path: Path) -> None:
    """A SubagentStop for an id that never started (out-of-order delivery,
    or a subagent dispatched before ccwork launched) changes nothing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_SUBAGENT_STOP, rid, _agent("ghost"))
    assert model.subagents(rid) == 0
    assert model.index(0).data(ROLE_SUBAGENTS) == 0

    model.apply_hook_event(EVENT_SUBAGENT_START, rid, _agent("a1"))
    model.apply_hook_event(EVENT_SUBAGENT_STOP, rid, _agent("ghost"))
    assert model.subagents(rid) == 1


def test_stop_does_not_clear_subagents(qapp, tmp_path: Path) -> None:
    """Background subagents outlive the main turn's Stop; the set survives
    until SubagentStop arrives so the left-edge twinkle keeps painting
    alongside the green DONE dot."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, rid)
    model.apply_hook_event(EVENT_SUBAGENT_START, rid, _agent("a1"))
    model.apply_hook_event(EVENT_STOP, rid)

    assert model.index(0).data(ROLE_WORKING) is False
    assert model.index(0).data(ROLE_STATUS) == STATUS_DONE
    assert model.subagents(rid) == 1


def test_subagents_coexist_with_attention(qapp, tmp_path: Path) -> None:
    """A permission request mid-turn can arrive while subagents are in
    flight. The two states are independent — neither clobbers the other."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_SUBAGENT_START, rid, _agent("a1"))
    model.apply_hook_event(
        EVENT_NOTIFICATION, rid, {"notification_type": "permission_prompt"},
    )

    assert model.index(0).data(ROLE_STATUS) == STATUS_ATTENTION
    assert model.subagents(rid) == 1


def test_subagents_coexist_with_working(qapp, tmp_path: Path) -> None:
    """Subagents dispatched mid-turn fire alongside the working spinner.
    Both axes are live simultaneously — the delegate paints the twinkle
    on the left while the braille spinner runs on the right."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = _store_with(str(repo), tmp_path / "repos.json")
    model = RepoListModel(store)
    rid = store.repos[0].id

    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, rid)
    model.apply_hook_event(EVENT_SUBAGENT_START, rid, _agent("a1"))

    assert model.index(0).data(ROLE_WORKING) is True
    assert model.subagents(rid) == 1
