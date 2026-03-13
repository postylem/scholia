"""Tests for scholia.comments — JSONL annotation store."""

import json

import pytest

from scholia.comments import (
    annotation_path,
    append_comment,
    append_reply,
    list_open,
    load_comments,
    resolve,
    unresolve,
)


def test_annotation_path(tmp_doc):
    p = annotation_path(tmp_doc)
    assert p.name == "test.md.scholia.jsonl"


def test_load_empty(tmp_doc):
    """No JSONL file returns empty list."""
    assert load_comments(tmp_doc) == []


def test_append_and_load(tmp_doc):
    """Create comment, load it back, verify fields."""
    ann = append_comment(tmp_doc, exact="Some text", prefix="", suffix="", body_text="hello")
    loaded = load_comments(tmp_doc)
    assert len(loaded) == 1
    assert loaded[0]["id"] == ann["id"]
    assert loaded[0]["target"]["selector"]["exact"] == "Some text"
    assert loaded[0]["body"][0]["value"] == "hello"
    assert loaded[0]["scholia:status"] == "open"


def test_append_reply(tmp_doc):
    """Create comment, add reply, verify thread has 2 messages."""
    ann = append_comment(tmp_doc, exact="Some text", body_text="question")
    append_reply(tmp_doc, ann["id"], "answer", creator="ai")
    loaded = load_comments(tmp_doc)
    assert len(loaded) == 1
    assert len(loaded[0]["body"]) == 2
    assert loaded[0]["body"][1]["value"] == "answer"
    assert loaded[0]["body"][1]["creator"]["name"] == "ai"


def test_reply_not_found(tmp_doc):
    """Reply to nonexistent ID raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        append_reply(tmp_doc, "urn:uuid:nonexistent", "text")


def test_dedup_by_id(tmp_doc):
    """Append two versions of same annotation, load returns latest."""
    ann = append_comment(tmp_doc, exact="text", body_text="v1")
    append_reply(tmp_doc, ann["id"], "v2 reply")
    loaded = load_comments(tmp_doc)
    assert len(loaded) == 1
    assert len(loaded[0]["body"]) == 2


def test_corrupt_line_skipped(tmp_doc, capsys):
    """JSONL with a corrupt line still loads valid annotations."""
    append_comment(tmp_doc, exact="good", body_text="valid")
    p = annotation_path(tmp_doc)
    with open(p, "a") as f:
        f.write("this is not json\n")
    append_comment(tmp_doc, exact="also good", body_text="also valid")
    loaded = load_comments(tmp_doc)
    assert len(loaded) == 2
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower()


def test_list_open(tmp_doc):
    """Filters to only open-status annotations."""
    ann1 = append_comment(tmp_doc, exact="open one", body_text="hi")
    ann2 = append_comment(tmp_doc, exact="will resolve", body_text="bye")
    resolve(tmp_doc, ann2["id"])
    open_anns = list_open(tmp_doc)
    assert len(open_anns) == 1
    assert open_anns[0]["id"] == ann1["id"]


def test_resolve(tmp_doc):
    """Resolve sets status and resolvedAt timestamp."""
    ann = append_comment(tmp_doc, exact="text", body_text="hi")
    resolved = resolve(tmp_doc, ann["id"])
    assert resolved["scholia:status"] == "resolved"
    assert "scholia:resolvedAt" in resolved
    assert len(resolved["body"]) == 1


def test_unresolve(tmp_doc):
    """Unresolve clears status back to open."""
    ann = append_comment(tmp_doc, exact="text", body_text="hi")
    resolve(tmp_doc, ann["id"])
    unresolved = unresolve(tmp_doc, ann["id"])
    assert unresolved["scholia:status"] == "open"
    assert unresolved.get("scholia:resolvedAt") is None


def test_resolve_not_found(tmp_doc):
    """Resolve nonexistent ID raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        resolve(tmp_doc, "urn:uuid:nonexistent")
