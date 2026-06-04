"""Crash-recovery session tracking (src/core/session_recovery.py)."""

import json

from src.core import session_recovery as sr


def _doc(path):
    return json.loads(path.read_text())


def test_record_open_creates_entry(tmp_path):
    p = tmp_path / "open_sessions.json"
    sr.record_open("/repo/a", "sid-1", "a", path=p)
    assert _doc(p)["open"] == {"/repo/a": {"id": "sid-1", "name": "a"}}


def test_record_open_is_idempotent(tmp_path):
    p = tmp_path / "open_sessions.json"
    sr.record_open("/repo/a", "sid-1", "a", path=p)
    mtime = p.stat().st_mtime_ns
    # Same id again → no rewrite.
    sr.record_open("/repo/a", "sid-1", "a", path=p)
    assert p.stat().st_mtime_ns == mtime


def test_record_open_new_id_overwrites(tmp_path):
    p = tmp_path / "open_sessions.json"
    sr.record_open("/repo/a", "sid-1", "a", path=p)
    sr.record_open("/repo/a", "sid-2", "a", path=p)
    assert _doc(p)["open"]["/repo/a"]["id"] == "sid-2"


def test_clear_open_removes_one(tmp_path):
    p = tmp_path / "open_sessions.json"
    sr.record_open("/repo/a", "sid-1", "a", path=p)
    sr.record_open("/repo/b", "sid-2", "b", path=p)
    sr.clear_open("/repo/a", path=p)
    assert set(_doc(p)["open"]) == {"/repo/b"}


def test_promote_folds_open_into_recovery(tmp_path):
    p = tmp_path / "open_sessions.json"
    sr.record_open("/repo/a", "sid-1", "a", path=p)
    sr.record_open("/repo/b", "sid-2", "b", path=p)
    crashed = sr.promote_crashes(path=p)
    assert {e["path"] for e in crashed} == {"/repo/a", "/repo/b"}
    assert {e["id"] for e in crashed} == {"sid-1", "sid-2"}
    # open is emptied; recovery now holds them.
    doc = _doc(p)
    assert doc["open"] == {}
    assert set(doc["recovery"]) == {"/repo/a", "/repo/b"}


def test_clean_quit_then_launch_shows_nothing(tmp_path):
    p = tmp_path / "open_sessions.json"
    sr.record_open("/repo/a", "sid-1", "a", path=p)
    sr.clear_all_open(path=p)            # clean quit
    assert sr.promote_crashes(path=p) == []


def test_crash_then_launch_shows_banner(tmp_path):
    p = tmp_path / "open_sessions.json"
    sr.record_open("/repo/a", "sid-1", "a", path=p)
    # No clean quit (no clear_all_open) — simulate crash, then relaunch.
    crashed = sr.promote_crashes(path=p)
    assert [e["path"] for e in crashed] == ["/repo/a"]


def test_recovery_persists_until_dismissed(tmp_path):
    p = tmp_path / "open_sessions.json"
    sr.record_open("/repo/a", "sid-1", "a", path=p)
    sr.promote_crashes(path=p)           # first launch after crash
    # Second launch with nothing newly open: banner still there.
    assert [e["path"] for e in sr.promote_crashes(path=p)] == ["/repo/a"]
    sr.dismiss(path=p)
    assert sr.promote_crashes(path=p) == []


def test_fresh_session_clears_stale_recovery(tmp_path):
    p = tmp_path / "open_sessions.json"
    sr.record_open("/repo/a", "sid-1", "a", path=p)
    sr.promote_crashes(path=p)           # /repo/a now in recovery
    # User resumes /repo/a — a new session for that path drops the banner row.
    sr.record_open("/repo/a", "sid-2", "a", path=p)
    assert _doc(p)["recovery"] == {}


def test_corrupt_file_is_ignored(tmp_path):
    p = tmp_path / "open_sessions.json"
    p.write_text("{ not json")
    assert sr.promote_crashes(path=p) == []
    # And still writable afterwards.
    sr.record_open("/repo/a", "sid-1", "a", path=p)
    assert _doc(p)["open"]["/repo/a"]["id"] == "sid-1"
