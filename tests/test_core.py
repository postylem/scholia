"""Tests for scholia core: comments store, read/unread state, and CLI."""

import json
import subprocess
import sys
from datetime import datetime

import pytest

from scholia.comments import (
    annotation_path,
    append_comment,
    append_reply,
    edit_body,
    list_open,
    load_comments,
    resolve,
    unresolve,
)
from scholia.state import is_unread, load_state, mark_read, mark_unread, state_path


# ── Comments store ─────────────────────────────────────


def test_annotation_path(tmp_doc):
    assert annotation_path(tmp_doc).name == "test.md.scholia.jsonl"


def test_append_load_reply(tmp_doc):
    """Full lifecycle: create, load, reply, verify thread."""
    ann = append_comment(tmp_doc, exact="Some text", body_text="hello")
    loaded = load_comments(tmp_doc)
    assert len(loaded) == 1
    assert loaded[0]["target"]["selector"]["exact"] == "Some text"
    assert loaded[0]["body"][0]["value"] == "hello"
    assert loaded[0]["scholia:status"] == "open"

    append_reply(tmp_doc, ann["id"], "answer", creator="ai")
    loaded = load_comments(tmp_doc)
    assert len(loaded[0]["body"]) == 2
    assert loaded[0]["body"][1]["creator"]["name"] == "ai"
    assert loaded[0]["body"][1]["creator"]["type"] == "Software"


def test_resolve_unresolve(tmp_doc):
    """Resolve sets status + timestamp; unresolve clears both."""
    ann = append_comment(tmp_doc, exact="text", body_text="hi")
    resolved = resolve(tmp_doc, ann["id"])
    assert resolved["scholia:status"] == "resolved"
    assert "scholia:resolvedAt" in resolved

    unresolved = unresolve(tmp_doc, ann["id"])
    assert unresolved["scholia:status"] == "open"
    assert unresolved.get("scholia:resolvedAt") is None


def test_list_open_filter(tmp_doc):
    ann1 = append_comment(tmp_doc, exact="keep", body_text="hi")
    ann2 = append_comment(tmp_doc, exact="close", body_text="bye")
    resolve(tmp_doc, ann2["id"])
    open_anns = list_open(tmp_doc)
    assert len(open_anns) == 1
    assert open_anns[0]["id"] == ann1["id"]


def test_edit_body(tmp_doc):
    """edit_body replaces last body entry's value."""
    ann = append_comment(tmp_doc, exact="text", body_text="original")
    append_reply(tmp_doc, ann["id"], "reply text")
    edited = edit_body(tmp_doc, ann["id"], "edited reply")
    loaded = load_comments(tmp_doc)
    assert len(loaded) == 1
    assert loaded[0]["body"][-1]["value"] == "edited reply"
    assert "modified" in loaded[0]["body"][-1]
    assert loaded[0]["body"][0]["value"] == "original"  # first body unchanged


def test_edit_body_missing_id(tmp_doc):
    with pytest.raises(ValueError, match="not found"):
        edit_body(tmp_doc, "urn:uuid:nonexistent", "text")


def test_dedup_by_id(tmp_doc):
    """Append-only JSONL deduplicates by id (last version wins)."""
    ann = append_comment(tmp_doc, exact="text", body_text="v1")
    append_reply(tmp_doc, ann["id"], "v2 reply")
    assert len(load_comments(tmp_doc)) == 1


def test_corrupt_line_skipped(tmp_doc, capsys):
    append_comment(tmp_doc, exact="good", body_text="valid")
    with open(annotation_path(tmp_doc), "a") as f:
        f.write("this is not json\n")
    append_comment(tmp_doc, exact="also good", body_text="also valid")
    assert len(load_comments(tmp_doc)) == 2
    assert "warning" in capsys.readouterr().err.lower()


def test_error_on_missing_id(tmp_doc):
    with pytest.raises(ValueError, match="not found"):
        append_reply(tmp_doc, "urn:uuid:nonexistent", "text")
    with pytest.raises(ValueError, match="not found"):
        resolve(tmp_doc, "urn:uuid:nonexistent")


# ── Read/unread state ──────────────────────────────────


def test_state_read_unread_cycle(tmp_doc):
    """mark_read → mark_unread → mark_read lifecycle."""
    assert load_state(tmp_doc) == {}

    mark_read(tmp_doc, "urn:uuid:test-1")
    s = load_state(tmp_doc)
    ts = s["urn:uuid:test-1"]["lastReadAt"]
    assert datetime.fromisoformat(ts).tzinfo is not None

    mark_unread(tmp_doc, "urn:uuid:test-1")
    assert load_state(tmp_doc)["urn:uuid:test-1"]["lastReadAt"] is None

    mark_read(tmp_doc, "urn:uuid:test-1")
    mark_read(tmp_doc, "urn:uuid:test-2")
    s = load_state(tmp_doc)
    assert "urn:uuid:test-1" in s and "urn:uuid:test-2" in s

    # File is valid JSON (atomic writes)
    json.loads(state_path(tmp_doc).read_text())


def test_corrupt_state(tmp_doc, capsys):
    state_path(tmp_doc).write_text("not valid json{{{")
    assert load_state(tmp_doc) == {}


def test_is_unread_logic():
    ann = {"body": [{"created": "2026-03-12T14:00:00+00:00"}]}
    assert is_unread(ann, None) is True
    assert is_unread(ann, {"lastReadAt": None}) is True
    assert is_unread(ann, {"lastReadAt": "2026-03-12T12:00:00+00:00"}) is True
    assert is_unread(ann, {"lastReadAt": "2026-03-12T16:00:00+00:00"}) is False


# ── CLI ────────────────────────────────────────────────


def _run_cli(*args):
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", *args],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout, result.stderr


def test_cli_comment_reply_resolve(tmp_doc):
    """Full CLI flow: comment → list → reply → resolve → unresolve."""
    code, out, _ = _run_cli("comment", str(tmp_doc), "Some text", "A comment")
    assert code == 0 and "Comment created" in out

    code, out, _ = _run_cli("list", str(tmp_doc))
    assert "1 message(s)" in out

    ann_id = load_comments(tmp_doc)[0]["id"]
    code, _, _ = _run_cli("reply", str(tmp_doc), ann_id, "answer")
    assert code == 0
    assert len(load_comments(tmp_doc)[0]["body"]) == 2

    code, out, _ = _run_cli("resolve", str(tmp_doc), ann_id)
    assert code == 0 and "Resolved" in out

    code, out, _ = _run_cli("list", str(tmp_doc), "--open")
    assert ann_id not in out

    code, out, _ = _run_cli("list", str(tmp_doc), "--all")
    assert ann_id in out

    code, _, _ = _run_cli("unresolve", str(tmp_doc), ann_id)
    assert code == 0
    assert load_comments(tmp_doc)[0]["scholia:status"] == "open"


def test_cli_edit(tmp_doc):
    """CLI edit replaces the last body entry."""
    append_comment(tmp_doc, exact="text", body_text="first")
    ann_id = load_comments(tmp_doc)[0]["id"]
    append_reply(tmp_doc, ann_id, "second")
    code, out, _ = _run_cli("edit", str(tmp_doc), ann_id, "edited second")
    assert code == 0 and "Edited" in out
    assert load_comments(tmp_doc)[0]["body"][-1]["value"] == "edited second"


def test_cli_version():
    """scholia --version prints version string."""
    code, out, _ = _run_cli("--version")
    assert code == 0 and "scholia" in out


def test_cli_error_cases(tmp_doc):
    """Bad inputs return non-zero exit codes."""
    code, _, err = _run_cli("view", "/nonexistent/doc.md")
    assert code == 1

    code, _, _ = _run_cli("reply", str(tmp_doc), "urn:uuid:fake", "text")
    assert code == 1

    code, _, _ = _run_cli("list", str(tmp_doc), "--since", "not-a-date")
    assert code == 1


def test_cli_list_since(tmp_doc):
    ann = append_comment(tmp_doc, exact="text", body_text="hi")
    code, out, _ = _run_cli("list", str(tmp_doc), "--since", "2020-01-01")
    assert code == 0 and ann["id"] in out
