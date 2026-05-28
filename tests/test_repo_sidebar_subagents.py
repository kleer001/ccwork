"""Coverage for the subagent counter and its left-edge twinkle indicator.

A subagent dispatch (PreToolUse with tool_name in {"Task", "Agent"} — Claude
Code renamed the tool; we accept both) bumps the per-path counter on the
model. SubagentStop decrements it. While the counter is positive, the
delegate paints the SUBAGENT_FRAMES twinkle (·→✦→✶→❋→✶→✦) on the LEFT
edge of the row, alongside whatever the right-edge column is showing —
working spinner during the main turn, green DONE dot after Stop, etc.

Foreground and background subagents both count; the indicators are
visually separate so the user can tell parallel work is in flight.
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


def _pre_tool_use_payload(tool_name: str, **tool_input) -> dict:
    return {"tool_name": tool_name, "tool_input": tool_input}


@pytest.mark.parametrize("tool_name", ["Task", "Agent"])
def test_subagent_dispatch_increments_counter(qapp, tmp_path: Path, tool_name: str) -> None:
    """Claude Code renamed Task → Agent; the matcher must accept both."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    payload = _pre_tool_use_payload(tool_name, subagent_type="general-purpose")
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)

    assert model.index(0).data(ROLE_SUBAGENTS) == 1
    assert model.subagents(str(repo)) == 1


def test_foreground_subagent_dispatch_is_counted(qapp, tmp_path: Path) -> None:
    """Foreground subagents count too — the left-edge twinkle paints
    alongside the right-edge working spinner so parallel work is visible
    during the main turn, not just after it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    payload = _pre_tool_use_payload("Agent", subagent_type="general-purpose")
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    assert model.subagents(str(repo)) == 1

    payload = _pre_tool_use_payload(
        "Agent", subagent_type="general-purpose", run_in_background=False,
    )
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    assert model.subagents(str(repo)) == 2


def test_non_subagent_pre_tool_use_is_ignored(qapp, tmp_path: Path) -> None:
    """We register PreToolUse with matcher 'Task', but defensive: even if
    a non-subagent PreToolUse reaches the model (manual config / future
    change), it must not increment the counter."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    model.apply_hook_event(
        EVENT_PRE_TOOL_USE, str(repo),
        _pre_tool_use_payload("Bash", command="ls"),
    )
    assert model.subagents(str(repo)) == 0


def test_subagent_stop_decrements_counter(qapp, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    payload = _pre_tool_use_payload("Agent", subagent_type="general-purpose")
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    assert model.subagents(str(repo)) == 2

    model.apply_hook_event(EVENT_SUBAGENT_STOP, str(repo))
    assert model.subagents(str(repo)) == 1

    model.apply_hook_event(EVENT_SUBAGENT_STOP, str(repo))
    assert model.subagents(str(repo)) == 0


def test_subagent_stop_clamps_at_zero(qapp, tmp_path: Path) -> None:
    """A SubagentStop without a matching dispatch (out-of-order delivery)
    must not push the counter negative."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    model.apply_hook_event(EVENT_SUBAGENT_STOP, str(repo))
    model.apply_hook_event(EVENT_SUBAGENT_STOP, str(repo))
    assert model.subagents(str(repo)) == 0
    assert model.index(0).data(ROLE_SUBAGENTS) == 0


def test_stop_does_not_clear_subagents(qapp, tmp_path: Path) -> None:
    """Background subagents outlive the main turn's Stop; the counter
    survives until SubagentStop arrives so the left-edge twinkle keeps
    painting alongside the green DONE dot."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, str(repo))
    payload = _pre_tool_use_payload("Agent", subagent_type="general-purpose")
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    model.apply_hook_event(EVENT_STOP, str(repo))

    assert model.index(0).data(ROLE_WORKING) is False
    assert model.index(0).data(ROLE_STATUS) == STATUS_DONE
    assert model.subagents(str(repo)) == 1


def test_subagents_coexist_with_attention(qapp, tmp_path: Path) -> None:
    """Notification fires mid-turn; subagents may already be in flight.
    The two states are independent — neither should clobber the other."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    payload = _pre_tool_use_payload("Agent", subagent_type="general-purpose")
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    model.apply_hook_event(EVENT_NOTIFICATION, str(repo))

    assert model.index(0).data(ROLE_STATUS) == STATUS_ATTENTION
    assert model.subagents(str(repo)) == 1


def test_subagents_coexist_with_working(qapp, tmp_path: Path) -> None:
    """Subagents dispatched mid-turn fire alongside the working spinner.
    Both axes are live simultaneously — the delegate paints the twinkle
    on the left while the braille spinner runs on the right."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, str(repo))
    payload = _pre_tool_use_payload("Agent", subagent_type="general-purpose")
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)

    assert model.index(0).data(ROLE_WORKING) is True
    assert model.subagents(str(repo)) == 1
