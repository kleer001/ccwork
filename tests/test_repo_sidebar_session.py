"""Coverage for the session-active flag and its cascade-clear on SessionEnd.

The two ambient badges (⠿ when a Claude session is live, ▌ when only the
bare terminal is open) ride a single per-path boolean: `_session_active`.
SessionStart flips it on, SessionEnd flips it off AND cascade-clears the
per-session signals (`_status`, `_working`, `_subagents`, `_turn_started`)
that would otherwise mask the bare-terminal indicator.
"""

from __future__ import annotations

from pathlib import Path

from src.core.hook_server import (
    EVENT_NOTIFICATION,
    EVENT_PRE_TOOL_USE,
    EVENT_SESSION_END,
    EVENT_SESSION_START,
    EVENT_STOP,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore
from src.ui.repo_sidebar import (
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
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    assert model.index(0).data(ROLE_SESSION_ACTIVE) is False
    model.apply_hook_event(EVENT_SESSION_START, str(repo))
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is True
    assert model.is_session_active(str(repo)) is True


def test_session_end_clears_active_and_status(qapp, tmp_path: Path) -> None:
    """Exiting Claude makes any leftover DONE/ATTENTION dot stale —
    cascade-clear so the ▌ ambient badge isn't masked."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    model.apply_hook_event(EVENT_SESSION_START, str(repo))
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, str(repo))
    model.apply_hook_event(EVENT_STOP, str(repo))
    assert model.index(0).data(ROLE_STATUS) == STATUS_DONE

    model.apply_hook_event(EVENT_SESSION_END, str(repo))
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is False
    assert model.index(0).data(ROLE_STATUS) == ""
    assert model.index(0).data(ROLE_WORKING) is False


def test_session_end_clears_stuck_working(qapp, tmp_path: Path) -> None:
    """If a session is killed mid-turn, the working flag is stuck True
    without a Stop. SessionEnd must clear it so the spinner stops."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    model.apply_hook_event(EVENT_SESSION_START, str(repo))
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, str(repo))
    assert model.index(0).data(ROLE_WORKING) is True

    model.apply_hook_event(EVENT_SESSION_END, str(repo))
    assert model.index(0).data(ROLE_WORKING) is False
    assert model.any_working() is False


def test_session_end_clears_subagents(qapp, tmp_path: Path) -> None:
    """Subagents don't outlive their parent session — clear the counter
    on SessionEnd so a stale SubagentStop that arrives late can't drive
    it below zero (well, the clamp would catch that, but the indicator
    would still flicker)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "general-purpose"},
    }
    model.apply_hook_event(EVENT_SESSION_START, str(repo))
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    assert model.subagents(str(repo)) == 2

    model.apply_hook_event(EVENT_SESSION_END, str(repo))
    assert model.subagents(str(repo)) == 0
    assert model.index(0).data(ROLE_SUBAGENTS) == 0
    assert model.any_subagents() is False


def test_session_end_clears_attention(qapp, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    model.apply_hook_event(EVENT_SESSION_START, str(repo))
    model.apply_hook_event(EVENT_NOTIFICATION, str(repo))
    assert model.index(0).data(ROLE_STATUS) == STATUS_ATTENTION

    model.apply_hook_event(EVENT_SESSION_END, str(repo))
    assert model.index(0).data(ROLE_STATUS) == ""


def test_clear_session_tears_down_on_exit(qapp, tmp_path: Path) -> None:
    """`/exit` gets no SessionEnd hook (anthropics/claude-code#17885), so
    the terminal-process exit calls clear_session directly. It must match
    the SessionEnd cascade: a stuck working spinner and a leaked subagent
    twinkle both clear, so nothing animates forever after `/exit`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "general-purpose"},
    }
    model.apply_hook_event(EVENT_SESSION_START, str(repo))
    model.apply_hook_event(EVENT_USER_PROMPT_SUBMIT, str(repo))
    model.apply_hook_event(EVENT_PRE_TOOL_USE, str(repo), payload)
    assert model.any_working() is True
    assert model.any_subagents() is True

    model.clear_session(str(repo))
    assert model.any_working() is False
    assert model.any_subagents() is False
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is False


def test_relaunch_clears_x_indicator(qapp, tmp_path: Path) -> None:
    """User exits Claude (⠿→▌), then types `claude` again. The next
    SessionStart must flip session_active back to True so the ⠿ returns."""
    repo = tmp_path / "repo"
    repo.mkdir()
    model = RepoListModel(_store_with(str(repo), tmp_path / "repos.json"))

    model.apply_hook_event(EVENT_SESSION_START, str(repo))
    model.apply_hook_event(EVENT_SESSION_END, str(repo))
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is False

    model.apply_hook_event(EVENT_SESSION_START, str(repo))
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is True


def test_session_active_is_path_keyed(qapp, tmp_path: Path) -> None:
    """Two repos: a session on one must not leak into the other."""
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path=str(a)), Repo(path=str(b))]
    model = RepoListModel(store)

    model.apply_hook_event(EVENT_SESSION_START, str(a))
    assert model.index(0).data(ROLE_SESSION_ACTIVE) is True
    assert model.index(1).data(ROLE_SESSION_ACTIVE) is False
