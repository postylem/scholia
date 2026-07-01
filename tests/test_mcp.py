"""Tests for the MCP review server helpers (no network, no real subprocess)."""

import asyncio

import aiohttp
import pytest

from scholia.comments import append_comment
from scholia.mcp_server import (
    _await_submission,
    _format_review_payload,
    _run_request_review,
)

# ── Fake aiohttp session for the long-poll loop ──────────


class _FakeResp:
    def __init__(self, status, data):
        self.status = status
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self):
        return self._data


class _FakeHttp:
    """Returns queued (status, data) tuples; raises if `raise_exc` is set."""

    def __init__(self, responses=None, raise_exc=None):
        self._responses = list(responses or [])
        self._raise = raise_exc

    def get(self, url, params=None, timeout=None):
        if self._raise:
            raise self._raise
        status, data = self._responses.pop(0)
        return _FakeResp(status, data)


# ── _format_review_payload ───────────────────────────────


def test_format_payload_includes_context_and_body(tmp_doc):
    ann = append_comment(
        tmp_doc,
        exact="Some text",
        body_text="Is this clear?",
        source_selector={"exact": "Some text"},
    )
    out = _format_review_payload(tmp_doc, [ann["id"]], "submit", "")
    assert "1 comment" in out
    assert "Is this clear?" in out
    assert str(tmp_doc) in out  # file reference
    assert "request_review again" in out  # next-round guidance


def test_format_payload_finish_says_complete(tmp_doc):
    ann = append_comment(tmp_doc, exact="Some text", body_text="last one")
    out = _format_review_payload(tmp_doc, [ann["id"]], "finish", "all good")
    assert "COMPLETE" in out
    assert "all good" in out  # the human's note
    assert "do NOT call request_review again" in out


def test_format_payload_empty_finish(tmp_doc):
    out = _format_review_payload(tmp_doc, [], "finish", "")
    assert "without selecting comments" in out


def test_format_payload_single_line_includes_end_column(tmp_doc):
    """The file reference mirrors `scholia list`: a single-line selection still
    carries its end column (e.g. ':7:1-10'), not just the start."""
    ann = append_comment(
        tmp_doc, exact="Some text", body_text="hi", source_selector={"exact": "Some text"}
    )
    out = _format_review_payload(tmp_doc, [ann["id"]], "submit", "")
    assert "7:1-10" in out


def test_format_payload_orphan_includes_original_context(tmp_doc):
    """An orphaned comment still shows its original prefix/exact/suffix context,
    so the agent knows what the comment referred to (mirrors `scholia list`)."""
    ann = append_comment(
        tmp_doc,
        exact="a phrase that is absent from the document",
        body_text="what about this?",
        source_selector={
            "exact": "a phrase that is absent from the document",
            "prefix": "unique-left-marker ",
            "suffix": " unique-right-marker",
        },
    )
    out = _format_review_payload(tmp_doc, [ann["id"]], "submit", "")
    assert "orphaned" in out
    # The original context (not just the bare "orphaned" line) must survive.
    assert "a phrase that is absent from the document" in out
    assert "unique-left-marker" in out


# ── _await_submission ────────────────────────────────────


@pytest.mark.asyncio
async def test_await_submission_returns_on_submit():
    http = _FakeHttp(
        [
            (200, {"status": "pending"}),
            (200, {"status": "submitted", "action": "submit", "comment_ids": ["x"]}),
        ]
    )
    result = await _await_submission(http, "http://x", "rev-1", chunk=0.001, overall=100)
    assert result["status"] == "submitted"
    assert result["comment_ids"] == ["x"]


@pytest.mark.asyncio
async def test_await_submission_times_out():
    http = _FakeHttp([(200, {"status": "pending"})])
    result = await _await_submission(http, "http://x", "rev-1", chunk=0.001, overall=0.0)
    assert result["status"] == "timeout"


@pytest.mark.asyncio
async def test_await_submission_unknown_session():
    http = _FakeHttp([(404, {"status": "unknown"})])
    result = await _await_submission(http, "http://x", "rev-1", chunk=0.001, overall=100)
    assert result["status"] == "unknown"


@pytest.mark.asyncio
async def test_await_submission_unreachable(monkeypatch):
    async def _no_sleep(_):
        return None

    monkeypatch.setattr("scholia.mcp_server.asyncio.sleep", _no_sleep)
    http = _FakeHttp(raise_exc=aiohttp.ClientError("boom"))
    result = await _await_submission(http, "http://x", "rev-1", chunk=0.001, overall=100)
    assert result["status"] == "unreachable"


# ── _run_request_review (guard paths) ────────────────────


@pytest.mark.asyncio
async def test_run_request_review_missing_doc(tmp_path):
    out = await _run_request_review(str(tmp_path / "nope.md"))
    assert "not found" in out


# ── FastMCP wiring (needs the optional `mcp` package) ────


def test_format_payload_general_comment(tmp_doc):
    from scholia.comments import append_general_comment

    ann = append_general_comment(tmp_doc, body_text="Does the math use standard notation?")
    out = _format_review_payload(tmp_doc, [ann["id"]], "submit", "")
    assert "general comment - about the whole document" in out
    assert "Does the math use standard notation?" in out
    assert "orphaned" not in out


def test_build_server_exposes_request_review():
    pytest.importorskip("mcp")
    from scholia.mcp_server import build_server

    server = build_server()
    tools = asyncio.run(server.list_tools())
    tool = next((t for t in tools if t.name == "request_review"), None)
    assert tool is not None
    props = tool.inputSchema.get("properties", {})
    assert "doc" in props
    assert "ctx" not in props  # Context is injected, not an agent-visible arg
