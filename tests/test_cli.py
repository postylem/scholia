"""Tests for scholia CLI commands."""

import subprocess
import sys

import pytest

from scholia.comments import append_comment, load_comments, resolve


def _run_cli(*args):
    """Run scholia CLI and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", *args],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout, result.stderr


def test_start_help():
    code, out, _ = _run_cli("start", "--help")
    assert code == 0
    assert "Start annotation server" in out


def test_comment_and_list(tmp_doc):
    code, out, _ = _run_cli("comment", str(tmp_doc), "Some text", "A comment")
    assert code == 0
    assert "Comment created" in out

    code, out, _ = _run_cli("list", str(tmp_doc))
    assert code == 0
    assert "Some text" in out
    assert "1 message(s)" in out


def test_reply_via_cli(tmp_doc):
    ann = append_comment(tmp_doc, exact="Some text", body_text="question")
    code, out, _ = _run_cli("reply", str(tmp_doc), ann["id"], "answer")
    assert code == 0
    loaded = load_comments(tmp_doc)
    assert len(loaded[0]["body"]) == 2


def test_list_open_filter(tmp_doc):
    ann1 = append_comment(tmp_doc, exact="open", body_text="hi")
    ann2 = append_comment(tmp_doc, exact="closed", body_text="bye")
    resolve(tmp_doc, ann2["id"])

    code, out, _ = _run_cli("list", str(tmp_doc), "--open")
    assert code == 0
    assert ann1["id"] in out
    assert ann2["id"] not in out


def test_resolve_cli(tmp_doc):
    ann = append_comment(tmp_doc, exact="text", body_text="hi")
    code, out, _ = _run_cli("resolve", str(tmp_doc), ann["id"])
    assert code == 0
    assert "Resolved" in out

    loaded = load_comments(tmp_doc)
    assert loaded[0]["scholia:status"] == "resolved"


def test_unresolve_cli(tmp_doc):
    ann = append_comment(tmp_doc, exact="text", body_text="hi")
    resolve(tmp_doc, ann["id"])
    code, out, _ = _run_cli("unresolve", str(tmp_doc), ann["id"])
    assert code == 0

    loaded = load_comments(tmp_doc)
    assert loaded[0]["scholia:status"] == "open"


def test_list_all(tmp_doc):
    ann1 = append_comment(tmp_doc, exact="open", body_text="hi")
    ann2 = append_comment(tmp_doc, exact="closed", body_text="bye")
    resolve(tmp_doc, ann2["id"])

    code, out, _ = _run_cli("list", str(tmp_doc), "--all")
    assert code == 0
    assert ann1["id"] in out
    assert ann2["id"] in out


def test_list_since(tmp_doc):
    ann = append_comment(tmp_doc, exact="text", body_text="hi")
    code, out, _ = _run_cli("list", str(tmp_doc), "--since", "2020-01-01")
    assert code == 0
    assert ann["id"] in out


def test_start_file_not_found():
    code, _, err = _run_cli("start", "/nonexistent/path/doc.md")
    assert code == 1
    assert "not found" in err.lower()


def test_reply_bad_id(tmp_doc):
    code, _, err = _run_cli("reply", str(tmp_doc), "urn:uuid:fake", "text")
    assert code == 1
    assert "not found" in err.lower()


def test_list_invalid_since(tmp_doc):
    code, _, err = _run_cli("list", str(tmp_doc), "--since", "not-a-date")
    assert code == 1
    assert "invalid" in err.lower() or "error" in err.lower()
