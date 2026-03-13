# tests/test_state.py
"""Tests for scholia.state — read/unread state management."""

import json
from datetime import datetime, timezone

from scholia.state import load_state, mark_read, mark_unread, state_path, is_unread


def test_state_path(tmp_doc):
    p = state_path(tmp_doc)
    assert p.name == "test.md.scholia.state.json"
    assert p.parent == tmp_doc.parent


def test_load_empty_state(tmp_doc):
    """No state file returns empty dict."""
    assert load_state(tmp_doc) == {}


def test_load_corrupt_state(tmp_doc, capsys):
    """Corrupt JSON returns empty dict and logs warning."""
    sp = state_path(tmp_doc)
    sp.write_text("not valid json{{{")
    result = load_state(tmp_doc)
    assert result == {}
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower() or "corrupt" in captured.err.lower()


def test_mark_read(tmp_doc):
    """mark_read sets lastReadAt to a UTC timestamp."""
    mark_read(tmp_doc, "urn:uuid:test-1")
    state = load_state(tmp_doc)
    assert "urn:uuid:test-1" in state
    ts = state["urn:uuid:test-1"]["lastReadAt"]
    assert ts is not None
    # Should be a valid ISO timestamp
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None


def test_mark_unread(tmp_doc):
    """mark_unread clears lastReadAt."""
    mark_read(tmp_doc, "urn:uuid:test-1")
    mark_unread(tmp_doc, "urn:uuid:test-1")
    state = load_state(tmp_doc)
    assert state["urn:uuid:test-1"]["lastReadAt"] is None


def test_mark_read_preserves_other_entries(tmp_doc):
    """Marking one annotation doesn't affect others."""
    mark_read(tmp_doc, "urn:uuid:test-1")
    mark_read(tmp_doc, "urn:uuid:test-2")
    state = load_state(tmp_doc)
    assert "urn:uuid:test-1" in state
    assert "urn:uuid:test-2" in state


def test_mark_read_atomic(tmp_doc):
    """State file should exist as valid JSON after write (no partial writes)."""
    mark_read(tmp_doc, "urn:uuid:test-1")
    sp = state_path(tmp_doc)
    # File must be valid JSON
    data = json.loads(sp.read_text())
    assert "urn:uuid:test-1" in data


def test_is_unread_no_state():
    """No lastReadAt means unread."""
    ann = {"body": [{"created": "2026-03-12T12:00:00+00:00"}]}
    assert is_unread(ann, None) is True


def test_is_unread_null_last_read():
    """Null lastReadAt means unread."""
    ann = {"body": [{"created": "2026-03-12T12:00:00+00:00"}]}
    assert is_unread(ann, {"lastReadAt": None}) is True


def test_is_unread_new_message():
    """Message newer than lastReadAt means unread."""
    ann = {"body": [{"created": "2026-03-12T14:00:00+00:00"}]}
    assert is_unread(ann, {"lastReadAt": "2026-03-12T12:00:00+00:00"}) is True


def test_all_read():
    """All messages older than lastReadAt means not unread."""
    ann = {"body": [{"created": "2026-03-12T10:00:00+00:00"}]}
    assert is_unread(ann, {"lastReadAt": "2026-03-12T12:00:00+00:00"}) is False
