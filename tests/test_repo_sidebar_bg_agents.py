"""Coverage for the background-agent counter and its twinkle indicator.

Background agents (Task tool dispatched with `run_in_background=True`) keep
running past the parent turn's Stop hook. The model tracks them via
`_bg_agents`, incremented on PreToolUse(Task, run_in_background=True) and
decremented on SubagentStop. When the count goes positive and the main turn
isn't working / attention, the badge column paints the animated
BG_AGENT_FRAMES twinkle (·→✦→✶→❋→✶→✦).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.hook_server import (
    EVENT_NOTIFICATION,
    EVENT_PRE_TOOL_USE,
    EVENT_STOP,
    EVENT_SUBAGENT_STOP,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore
from src.ui.repo_sidebar import (
    ROLE_BG_AGENTS,
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


def _pre_tool_use_payload(tool_name: str, **tool_input) -> dict:
    return {"tool_name": tool_name, "tool_input": tool_input}


def test_background_task_dispatch_increments_counter(qapp, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    payload = _pre_tool_use_payload(
        "Task", subagent_type="general-purpose", run_in_background=True,
    )
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)

    assert model.index(0).data(ROLE_BG_AGENTS) == 1
    assert model.bg_agents(str(repo)) == 1


def test_foreground_task_dispatch_is_ignored(qapp, tmp_path: Path) -> None:
    """run_in_background=False (or missing) is foreground — the working
    spinner already covers it, so we must not also count it as a
    background agent."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    payload = _pre_tool_use_payload("Task", subagent_type="general-purpose")
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    assert model.bg_agents(str(repo)) == 0

    payload = _pre_tool_use_payload(
        "Task", subagent_type="general-purpose", run_in_background=False,
    )
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    assert model.bg_agents(str(repo)) == 0


def test_non_task_pre_tool_use_is_ignored(qapp, tmp_path: Path) -> None:
    """We register PreToolUse with matcher 'Task', but defensive: even if
    a non-Task PreToolUse reaches the model (manual config / future change),
    it must not increment the counter."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    model.apply_hook_event(
        EVENT_PRE_TOOL_USE, str(repo),
        _pre_tool_use_payload("Bash", command="ls", run_in_background=True),
    )
    assert model.bg_agents(str(repo)) == 0


def test_subagent_stop_decrements_counter(qapp, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    payload = _pre_tool_use_payload(
        "Task", subagent_type="general-purpose", run_in_background=True,
    )
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    assert model.bg_agents(str(repo)) == 2

    model.apply_hook_event(EVENT_SUBAGENT_STOP, str(repo))
    assert model.bg_agents(str(repo)) == 1

    model.apply_hook_event(EVENT_SUBAGENT_STOP, str(repo))
    assert model.bg_agents(str(repo)) == 0


def test_subagent_stop_clamps_at_zero(qapp, tmp_path: Path) -> None:
    """Foreground subagents fire SubagentStop too, but we never incremented
    for them. The clamp must absorb those without going negative."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    model.apply_hook_event(EVENT_SUBAGENT_STOP, str(repo))
    model.apply_hook_event(EVENT_SUBAGENT_STOP, str(repo))
    assert model.bg_agents(str(repo)) == 0
    assert model.index(0).data(ROLE_BG_AGENTS) == 0


def test_stop_does_not_clear_bg_agents(qapp, tmp_path: Path) -> None:
    """The whole point of the indicator: detached agents outlive the main
    turn's Stop. The counter survives until SubagentStop arrives."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, str(repo))
    payload = _pre_tool_use_payload(
        "Task", subagent_type="general-purpose", run_in_background=True,
    )
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    model.apply_hook_event(EVENT_STOP, str(repo))

    assert model.index(0).data(ROLE_WORKING) is False
    assert model.index(0).data(ROLE_STATUS) == STATUS_DONE
    assert model.bg_agents(str(repo)) == 1


def test_bg_agents_coexist_with_attention(qapp, tmp_path: Path) -> None:
    """Notification fires mid-turn; bg agents may already be in flight.
    The two states are independent — neither should clobber the other."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    payload = _pre_tool_use_payload(
        "Task", subagent_type="general-purpose", run_in_background=True,
    )
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    model.apply_hook_event(EVENT_NOTIFICATION, str(repo))

    assert model.index(0).data(ROLE_STATUS) == STATUS_ATTENTION
    assert model.bg_agents(str(repo)) == 1
