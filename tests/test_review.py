"""Tests for the in-memory review session registry (human → AI handshake)."""

import asyncio

import pytest

from scholia.review import ReviewRegistry, ReviewSession


def test_session_starts_waiting(tmp_path):
    s = ReviewSession(tmp_path / "doc.md", instruction="check the proof")
    assert s.status == "waiting"
    assert s.id.startswith("rev-")
    pub = s.to_public()
    assert pub["session_id"] == s.id
    assert pub["instruction"] == "check the proof"
    assert pub["status"] == "waiting"


def test_registry_start_and_get(tmp_path):
    reg = ReviewRegistry()
    s = reg.start(tmp_path / "doc.md")
    assert reg.get(s.id) is s
    assert reg.get(None) is None
    assert reg.get("nope") is None


def test_find_active_filters_by_doc_and_status(tmp_path):
    reg = ReviewRegistry()
    a = reg.start(tmp_path / "a.md")
    b = reg.start(tmp_path / "b.md")
    assert reg.find_active(tmp_path / "a.md") == [a]
    assert reg.find_active(tmp_path / "b.md") == [b]
    # A finished session drops out of "active".
    a.submit(["urn:uuid:1"], final=True)
    assert reg.find_active(tmp_path / "a.md") == []


def test_remove(tmp_path):
    reg = ReviewRegistry()
    s = reg.start(tmp_path / "doc.md")
    reg.remove(s.id)
    assert reg.get(s.id) is None
    reg.remove(s.id)  # idempotent


def test_find_for_rejoin_prefers_active(tmp_path):
    reg = ReviewRegistry()
    s = reg.start(tmp_path / "doc.md")
    assert reg.find_for_rejoin(tmp_path / "doc.md") is s
    assert reg.find_for_rejoin(tmp_path / "other.md") is None


def test_find_for_rejoin_recovers_stranded_terminal_session(tmp_path):
    """A finished/aborted session whose final batch was never delivered is
    rejoinable, so a re-issued request_review picks it up instead of stranding it."""
    reg = ReviewRegistry()
    s = reg.start(tmp_path / "doc.md")
    s.submit(["urn:uuid:1"], final=True)  # 'Send & finish' -> done, batch undelivered
    assert s.status == "done"
    assert reg.find_active(tmp_path / "doc.md") == []  # not "active" (no banner)
    assert reg.find_for_rejoin(tmp_path / "doc.md") is s  # but still rejoinable

    a = reg.start(tmp_path / "aborted.md")
    a.abort("cancelled by user")
    assert reg.find_for_rejoin(tmp_path / "aborted.md") is a


def test_find_for_rejoin_skips_collected_terminal(tmp_path):
    """A terminal session whose batch was already drained is not rejoinable."""
    reg = ReviewRegistry()
    s = reg.start(tmp_path / "doc.md")
    s.submit(["urn:uuid:1"], final=True)
    s.drain_pending()  # agent collected the final batch
    assert s.has_pending() is False
    assert reg.find_for_rejoin(tmp_path / "doc.md") is None


@pytest.mark.asyncio
async def test_wait_returns_submitted_payload(tmp_path):
    s = ReviewSession(tmp_path / "doc.md")

    async def submit_soon():
        await asyncio.sleep(0.02)
        s.submit(["urn:uuid:1", "urn:uuid:2"], instruction="please fix")

    asyncio.ensure_future(submit_soon())
    payload = await s.wait(timeout=2.0)
    assert payload["action"] == "submit"
    assert payload["comment_ids"] == ["urn:uuid:1", "urn:uuid:2"]
    assert payload["instruction"] == "please fix"
    assert s.status == "working"


@pytest.mark.asyncio
async def test_wait_times_out(tmp_path):
    s = ReviewSession(tmp_path / "doc.md")
    payload = await s.wait(timeout=0.05)
    assert payload is None
    assert s.status == "waiting"


@pytest.mark.asyncio
async def test_submit_before_wait_is_buffered(tmp_path):
    """A submission that arrives before the agent polls is not lost."""
    s = ReviewSession(tmp_path / "doc.md")
    s.submit(["urn:uuid:1"])
    payload = await s.wait(timeout=0.05)
    assert payload["comment_ids"] == ["urn:uuid:1"]


@pytest.mark.asyncio
async def test_multiple_batches_delivered_in_order(tmp_path):
    s = ReviewSession(tmp_path / "doc.md")
    s.submit(["a"])
    s.submit(["b"])
    first = await s.wait(timeout=0.05)
    second = await s.wait(timeout=0.05)
    assert first["comment_ids"] == ["a"]
    assert second["comment_ids"] == ["b"]


@pytest.mark.asyncio
async def test_final_submit_marks_done(tmp_path):
    s = ReviewSession(tmp_path / "doc.md")
    s.submit(["a"], final=True)
    payload = await s.wait(timeout=0.05)
    assert payload["action"] == "finish"
    assert s.status == "done"


@pytest.mark.asyncio
async def test_abort_marks_aborted(tmp_path):
    s = ReviewSession(tmp_path / "doc.md")
    s.abort("cancelled by user")
    payload = await s.wait(timeout=0.05)
    assert payload["action"] == "abort"
    assert payload["reason"] == "cancelled by user"
    assert s.status == "aborted"


def test_mark_waiting_transition(tmp_path):
    s = ReviewSession(tmp_path / "doc.md")
    assert s.mark_waiting() is False  # already waiting
    s.submit(["a"])
    assert s.status == "working"
    assert s.mark_waiting() is True
    assert s.status == "waiting"
    assert s.mark_waiting() is False


@pytest.mark.asyncio
async def test_drain_pending_returns_remaining_batches(tmp_path):
    s = ReviewSession(tmp_path / "doc.md")
    s.submit(["a"])
    s.submit(["b"])
    first = await s.wait(timeout=0.05)
    rest = s.drain_pending()
    assert first["comment_ids"] == ["a"]
    assert [r["comment_ids"] for r in rest] == [["b"]]
    assert s.drain_pending() == []  # now empty
