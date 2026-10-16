"""Hook-event table for the badges: what each event sets and what clears it.

Covers docs/specs/hook-events.md: the badge table (status and word), the
clear table (including that an end event never clears a different badge),
the ignored Notification types, PermissionRequest and its tooltip text,
the compaction flag, and that the delegate paints every badge.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from src.core.hook_server import (
    EVENT_NOTIFICATION,
    EVENT_PERMISSION_REQUEST,
    EVENT_POST_COMPACT,
    EVENT_PRE_COMPACT,
    EVENT_SESSION_END,
    EVENT_STOP,
    EVENT_STOP_FAILURE,
    EVENT_USER_PROMPT_SUBMIT,
)
from src.core.repo_store import Repo, RepoStore
from src.ui.badge_theme import (
    COMPACT_COLOR,
    COMPACTING_LABEL,
    STATUS_ANSWER,
    STATUS_ATTENTION,
    STATUS_COLORS,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_USAGE_LIMIT,
)
from src.ui.repo_sidebar import (
    ROLE_COMPACTING,
    ROLE_STATUS,
    ROLE_STATUS_WORD,
    ROLE_WORKING,
    RepoDelegate,
    RepoListModel,
)


def _model(tmp_path: Path) -> tuple[RepoListModel, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoStore(config_path=tmp_path / "repos.json")
    store.repos = [Repo(path=str(repo))]
    model = RepoListModel(store)
    return model, store.repos[0].id


def _apply(model: RepoListModel, rid: str, event: str, payload=None) -> None:
    model.apply_hook_event(event, rid, payload)


def _status(model: RepoListModel) -> str:
    return model.index(0).data(ROLE_STATUS) or ""


def _word(model: RepoListModel) -> str:
    return model.index(0).data(ROLE_STATUS_WORD) or ""


def _notif(kind: str) -> dict:
    return {"notification_type": kind}


PERMISSION_PAYLOAD = {"tool_name": "Bash", "tool_input": {"command": "rm -rf build"}}

# How each badge is raised, as (event, payload) steps.
SHOW = {
    STATUS_ATTENTION: [(EVENT_PERMISSION_REQUEST, PERMISSION_PAYLOAD)],
    STATUS_ANSWER: [(EVENT_NOTIFICATION, _notif("elicitation_dialog"))],
    STATUS_ERROR: [(EVENT_STOP_FAILURE, {"error": "rate_limit"})],
    STATUS_USAGE_LIMIT: [(EVENT_NOTIFICATION, _notif("quota_auto_resume_disabled"))],
    STATUS_DONE: [(EVENT_STOP, None)],
}


def _show(model: RepoListModel, rid: str, badge: str) -> None:
    for event, payload in SHOW[badge]:
        _apply(model, rid, event, payload)
    assert _status(model) == badge


# ── Badge table: status and word ───────────────────────────────────────────

BADGE_TABLE = [
    (EVENT_PERMISSION_REQUEST, PERMISSION_PAYLOAD, STATUS_ATTENTION, "Needs permission"),
    (EVENT_NOTIFICATION, _notif("permission_prompt"), STATUS_ATTENTION, "Needs permission"),
    (EVENT_NOTIFICATION, _notif("elicitation_dialog"), STATUS_ANSWER, "Needs an answer"),
    (EVENT_NOTIFICATION, _notif("elicitation_url_dialog"), STATUS_ANSWER, "Needs an answer"),
    (EVENT_STOP_FAILURE, {"error": "rate_limit"}, STATUS_ERROR, "Rate limited"),
    (EVENT_STOP_FAILURE, {"error": "overloaded"}, STATUS_ERROR, "API overloaded"),
    (EVENT_STOP_FAILURE, {"error": "server_error"}, STATUS_ERROR, "API overloaded"),
    (EVENT_STOP_FAILURE, {"error": "authentication_failed"}, STATUS_ERROR, "Account problem"),
    (EVENT_STOP_FAILURE, {"error": "billing_error"}, STATUS_ERROR, "Account problem"),
    (EVENT_STOP_FAILURE, {"error": "account_on_hold"}, STATUS_ERROR, "Account problem"),
    (EVENT_STOP_FAILURE, {"error": "oauth_org_not_allowed"}, STATUS_ERROR, "Account problem"),
    (EVENT_STOP_FAILURE, {"error": "cloud_credential_error"}, STATUS_ERROR, "Account problem"),
    (EVENT_STOP_FAILURE, {"error": "max_output_tokens"}, STATUS_ERROR, "Output limit hit"),
    (EVENT_STOP_FAILURE, {"error": "invalid_request"}, STATUS_ERROR, "API error"),
    (EVENT_STOP_FAILURE, {"error": "model_not_found"}, STATUS_ERROR, "API error"),
    (EVENT_STOP_FAILURE, {"error": "unknown"}, STATUS_ERROR, "API error"),
    (EVENT_NOTIFICATION, _notif("quota_auto_resume_stale"), STATUS_USAGE_LIMIT,
     "Usage limit: press Enter"),
    (EVENT_NOTIFICATION, _notif("quota_auto_resume_disabled"), STATUS_USAGE_LIMIT,
     "Usage limit reached"),
    (EVENT_STOP, None, STATUS_DONE, "Done"),
]


@pytest.mark.parametrize("event, payload, status, word", BADGE_TABLE)
def test_badge_table_sets_status_and_word(
    qapp, tmp_path: Path, event: str, payload, status: str, word: str,
) -> None:
    model, rid = _model(tmp_path)
    _apply(model, rid, event, payload)
    assert _status(model) == status
    assert _word(model) == word
    assert model.index(0).data(Qt.ToolTipRole).splitlines()[0] == word


# ── Clear table ────────────────────────────────────────────────────────────

# (badge raised first, end event, payload, status after the end event)
CLEAR_TABLE = [
    (STATUS_ATTENTION, EVENT_STOP, None, STATUS_DONE),
    (STATUS_ATTENTION, EVENT_STOP_FAILURE, {"error": "rate_limit"}, STATUS_ERROR),
    (STATUS_ATTENTION, EVENT_USER_PROMPT_SUBMIT, None, ""),
    (STATUS_ATTENTION, EVENT_SESSION_END, None, ""),
    (STATUS_ANSWER, EVENT_NOTIFICATION, _notif("elicitation_complete"), ""),
    (STATUS_ANSWER, EVENT_NOTIFICATION, _notif("elicitation_response"), ""),
    (STATUS_ANSWER, EVENT_STOP, None, STATUS_DONE),
    (STATUS_ANSWER, EVENT_STOP_FAILURE, {"error": "rate_limit"}, STATUS_ERROR),
    (STATUS_ANSWER, EVENT_USER_PROMPT_SUBMIT, None, ""),
    (STATUS_ANSWER, EVENT_SESSION_END, None, ""),
    (STATUS_ERROR, EVENT_USER_PROMPT_SUBMIT, None, ""),
    (STATUS_ERROR, EVENT_SESSION_END, None, ""),
    (STATUS_USAGE_LIMIT, EVENT_NOTIFICATION, _notif("quota_auto_resume_fired"), ""),
    (STATUS_USAGE_LIMIT, EVENT_USER_PROMPT_SUBMIT, None, ""),
    (STATUS_USAGE_LIMIT, EVENT_SESSION_END, None, ""),
    (STATUS_DONE, EVENT_USER_PROMPT_SUBMIT, None, ""),
    (STATUS_DONE, EVENT_SESSION_END, None, ""),
]


@pytest.mark.parametrize("badge, event, payload, after", CLEAR_TABLE)
def test_clear_table_clears_badge(
    qapp, tmp_path: Path, badge: str, event: str, payload, after: str,
) -> None:
    model, rid = _model(tmp_path)
    _show(model, rid, badge)
    _apply(model, rid, event, payload)
    assert _status(model) == after
    if not after:
        assert _word(model) == ""


@pytest.mark.parametrize("badge, event, payload", [
    (STATUS_ATTENTION, EVENT_NOTIFICATION, _notif("elicitation_complete")),
    (STATUS_ATTENTION, EVENT_NOTIFICATION, _notif("elicitation_response")),
    (STATUS_ATTENTION, EVENT_NOTIFICATION, _notif("quota_auto_resume_fired")),
    (STATUS_ANSWER, EVENT_NOTIFICATION, _notif("quota_auto_resume_fired")),
    (STATUS_USAGE_LIMIT, EVENT_NOTIFICATION, _notif("elicitation_complete")),
    (STATUS_USAGE_LIMIT, EVENT_NOTIFICATION, _notif("elicitation_response")),
])
def test_end_event_does_not_clear_a_different_badge(
    qapp, tmp_path: Path, badge: str, event: str, payload,
) -> None:
    model, rid = _model(tmp_path)
    _show(model, rid, badge)
    _apply(model, rid, event, payload)
    assert _status(model) == badge


# ── Ignored Notification types ─────────────────────────────────────────────

IGNORED_PAYLOADS = [
    _notif("idle_prompt"),
    _notif("auth_success"),
    _notif("agent_needs_input"),
    _notif("agent_completed"),
    _notif("some_future_type"),
    {},
    None,
]


@pytest.mark.parametrize("payload", IGNORED_PAYLOADS)
@pytest.mark.parametrize("start", [None, STATUS_DONE, STATUS_ATTENTION])
def test_ignored_notification_changes_nothing(
    qapp, tmp_path: Path, payload, start,
) -> None:
    model, rid = _model(tmp_path)
    if start:
        _show(model, rid, start)
    before = (_status(model), _word(model), model.index(0).data(ROLE_WORKING))
    _apply(model, rid, EVENT_NOTIFICATION, payload)
    assert (_status(model), _word(model), model.index(0).data(ROLE_WORKING)) == before


# ── PermissionRequest and its tooltip ──────────────────────────────────────

def test_permission_request_sets_attention_with_tool_text(qapp, tmp_path: Path) -> None:
    model, rid = _model(tmp_path)
    _apply(model, rid, EVENT_PERMISSION_REQUEST, PERMISSION_PAYLOAD)

    assert _status(model) == STATUS_ATTENTION
    tip = model.index(0).data(Qt.ToolTipRole)
    assert tip.splitlines()[0] == "Needs permission"
    assert tip.splitlines()[-1] == "Bash: rm -rf build"


def test_permission_prompt_notification_keeps_tool_text(qapp, tmp_path: Path) -> None:
    model, rid = _model(tmp_path)
    _apply(model, rid, EVENT_PERMISSION_REQUEST, PERMISSION_PAYLOAD)
    _apply(model, rid, EVENT_NOTIFICATION, _notif("permission_prompt"))

    assert _status(model) == STATUS_ATTENTION
    assert model.index(0).data(Qt.ToolTipRole).splitlines()[-1] == "Bash: rm -rf build"


def test_pending_tool_text_clears_with_permission_badge(qapp, tmp_path: Path) -> None:
    model, rid = _model(tmp_path)
    _apply(model, rid, EVENT_PERMISSION_REQUEST, PERMISSION_PAYLOAD)
    _apply(model, rid, EVENT_STOP, None)

    assert "Bash" not in model.index(0).data(Qt.ToolTipRole)


def test_permission_request_summarizes_file_tools(qapp, tmp_path: Path) -> None:
    model, rid = _model(tmp_path)
    _apply(model, rid, EVENT_PERMISSION_REQUEST, {
        "tool_name": "Edit", "tool_input": {"file_path": "/x/y.py", "old_string": "a"},
    })
    assert model.index(0).data(Qt.ToolTipRole).splitlines()[-1] == "Edit: /x/y.py"


# ── Stop and StopFailure ───────────────────────────────────────────────────

def test_stop_clears_attention_and_sets_done(qapp, tmp_path: Path) -> None:
    model, rid = _model(tmp_path)
    _apply(model, rid, EVENT_PERMISSION_REQUEST, PERMISSION_PAYLOAD)
    _apply(model, rid, EVENT_STOP, None)
    assert _status(model) == STATUS_DONE


def test_stop_failure_clears_working(qapp, tmp_path: Path) -> None:
    model, rid = _model(tmp_path)
    _apply(model, rid, EVENT_USER_PROMPT_SUBMIT, None)
    assert model.index(0).data(ROLE_WORKING) is True

    _apply(model, rid, EVENT_STOP_FAILURE, {"error": "overloaded"})
    assert model.index(0).data(ROLE_WORKING) is False
    assert _status(model) == STATUS_ERROR


# ── Compaction ─────────────────────────────────────────────────────────────

def test_pre_compact_sets_compacting(qapp, tmp_path: Path) -> None:
    model, rid = _model(tmp_path)
    _apply(model, rid, EVENT_PRE_COMPACT, None)

    assert model.index(0).data(ROLE_COMPACTING) is True
    assert model.is_compacting(rid) is True
    assert model.index(0).data(Qt.ToolTipRole).splitlines()[0] == COMPACTING_LABEL


def test_compacting_does_not_clear_a_badge(qapp, tmp_path: Path) -> None:
    model, rid = _model(tmp_path)
    _show(model, rid, STATUS_ATTENTION)
    _apply(model, rid, EVENT_PRE_COMPACT, None)
    assert _status(model) == STATUS_ATTENTION


@pytest.mark.parametrize("event, payload", [
    (EVENT_POST_COMPACT, None),
    (EVENT_STOP, None),
    (EVENT_STOP_FAILURE, {"error": "unknown"}),
    (EVENT_USER_PROMPT_SUBMIT, None),
    (EVENT_SESSION_END, None),
])
def test_end_events_clear_compacting(qapp, tmp_path: Path, event: str, payload) -> None:
    model, rid = _model(tmp_path)
    _apply(model, rid, EVENT_PRE_COMPACT, None)
    _apply(model, rid, event, payload)
    assert model.index(0).data(ROLE_COMPACTING) is False
    assert model.is_compacting(rid) is False


# ── Delegate paint ─────────────────────────────────────────────────────────

_ROW = QRect(0, 0, 320, 60)
_RIGHT_EDGE = (260, 320)  # x range that holds the outboard badge slot


def _render(model: RepoListModel) -> QImage:
    delegate = RepoDelegate()
    image = QImage(_ROW.width(), _ROW.height(), QImage.Format_ARGB32)
    image.fill(Qt.white)
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.rect = QRect(_ROW)
    option.font = QApplication.font()
    option.palette = QApplication.palette()
    option.state = QStyle.State_Enabled
    delegate.paint(painter, option, model.index(0))
    painter.end()
    return image


def _has_color(image: QImage, color, tolerance: int = 60) -> bool:
    x0, x1 = _RIGHT_EDGE
    for y in range(image.height()):
        for x in range(x0, x1):
            px = image.pixelColor(x, y)
            if (abs(px.red() - color.red()) + abs(px.green() - color.green())
                    + abs(px.blue() - color.blue())) <= tolerance:
                return True
    return False


@pytest.mark.parametrize("badge", [STATUS_ATTENTION, STATUS_ANSWER, STATUS_ERROR,
                                   STATUS_USAGE_LIMIT, STATUS_DONE])
def test_delegate_paints_each_status_badge(qapp, tmp_path: Path, badge: str) -> None:
    model, rid = _model(tmp_path)
    baseline = _render(model)
    _show(model, rid, badge)
    image = _render(model)

    assert image != baseline
    assert _has_color(image, STATUS_COLORS[badge])


def test_delegate_paints_compacting_glyph(qapp, tmp_path: Path) -> None:
    model, rid = _model(tmp_path)
    baseline = _render(model)
    _apply(model, rid, EVENT_PRE_COMPACT, None)
    image = _render(model)

    assert image != baseline
    assert _has_color(image, COMPACT_COLOR)
