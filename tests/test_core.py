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
    short_id_map,
    unresolve,
)
from scholia.context import locate_anchor
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

    append_reply(tmp_doc, ann["id"], "answer", creator="AI", is_software=True)
    loaded = load_comments(tmp_doc)
    assert len(loaded[0]["body"]) == 2
    assert loaded[0]["body"][1]["creator"]["name"] == "AI"
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


def test_short_id_map_empty(tmp_doc):
    """Empty annotation file returns empty dict."""
    assert short_id_map(tmp_doc) == {}


def test_short_id_map_single(tmp_doc):
    """Single annotation gets 4-char prefix (floor)."""
    ann = append_comment(tmp_doc, exact="text", body_text="hi")
    mapping = short_id_map(tmp_doc)
    full_id = ann["id"]
    uuid_part = full_id.removeprefix("urn:uuid:")
    assert full_id in mapping
    assert mapping[full_id] == uuid_part[:4]


def test_short_id_map_collision(tmp_doc):
    """Colliding prefixes auto-extend beyond 4 chars."""
    a1 = append_comment(tmp_doc, exact="text1", body_text="one")
    a2 = append_comment(tmp_doc, exact="text2", body_text="two")
    from scholia.comments import annotation_path
    import json
    path = annotation_path(tmp_doc)
    lines = path.read_text().splitlines()
    obj1 = json.loads(lines[-2])
    obj2 = json.loads(lines[-1])
    obj1["id"] = "urn:uuid:abcd1111-0000-0000-0000-000000000000"
    obj2["id"] = "urn:uuid:abcd2222-0000-0000-0000-000000000000"
    path.write_text(json.dumps(obj1) + "\n" + json.dumps(obj2) + "\n")

    mapping = short_id_map(tmp_doc)
    assert len(mapping) == 2
    for short in mapping.values():
        assert len(short) >= 5
    shorts = list(mapping.values())
    assert shorts[0] != shorts[1]


def test_short_id_map_stability(tmp_doc):
    """Map includes ALL annotations (including resolved) for stable results."""
    a1 = append_comment(tmp_doc, exact="keep", body_text="hi")
    a2 = append_comment(tmp_doc, exact="close", body_text="bye")
    resolve(tmp_doc, a2["id"])
    mapping = short_id_map(tmp_doc)
    assert a1["id"] in mapping
    assert a2["id"] in mapping


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
    assert "A comment" in out  # default format shows messages

    code, out, _ = _run_cli("list", str(tmp_doc), "--format", "summary")
    assert "1 message(s)" in out  # summary format shows counts

    ann_id = load_comments(tmp_doc)[0]["id"]
    code, _, _ = _run_cli("reply", str(tmp_doc), ann_id, "answer")
    assert code == 0
    assert len(load_comments(tmp_doc)[0]["body"]) == 2

    code, out, _ = _run_cli("resolve", str(tmp_doc), ann_id)
    assert code == 0 and "Resolved" in out

    # Default is open-only; resolved thread should not appear
    code, out, _ = _run_cli("list", str(tmp_doc))
    assert ann_id not in out

    code, out, _ = _run_cli("list", str(tmp_doc), "--all")
    short_prefix = ann_id.removeprefix("urn:uuid:")[:4]
    assert short_prefix in out

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
    short_prefix = ann["id"].removeprefix("urn:uuid:")[:4]
    assert code == 0 and short_prefix in out


def test_cli_list_short_ids(tmp_doc):
    """Default listing shows short IDs, not full urn:uuid:..."""
    append_comment(tmp_doc, exact="Some text", body_text="hi")
    code, out, _ = _run_cli("list", str(tmp_doc))
    assert code == 0
    assert "urn:uuid:" not in out


def test_cli_list_no_open_tag(tmp_doc):
    """Default listing (open-only) omits [open] status tag."""
    ann = append_comment(tmp_doc, exact="Some text", body_text="hi")
    short_prefix = ann["id"].removeprefix("urn:uuid:")[:4]
    code, out, _ = _run_cli("list", str(tmp_doc))
    assert code == 0
    assert short_prefix in out
    assert "[open]" not in out


def test_cli_list_all_shows_status(tmp_doc):
    """--all listing shows [open]/[resolved] status tags."""
    ann = append_comment(tmp_doc, exact="Some text", body_text="hi")
    resolve(tmp_doc, ann["id"])
    code, out, _ = _run_cli("list", str(tmp_doc), "--all")
    assert code == 0
    assert "[resolved]" in out


def test_cli_list_message_count(tmp_doc):
    """Threads with >1 message show count in header."""
    ann = append_comment(tmp_doc, exact="Some text", body_text="first")
    append_reply(tmp_doc, ann["id"], "second")
    append_reply(tmp_doc, ann["id"], "third")
    code, out, _ = _run_cli("list", str(tmp_doc))
    assert code == 0
    assert "(3 messages)" in out


def test_cli_list_single_message_no_count(tmp_doc):
    """Single-message threads show no count."""
    append_comment(tmp_doc, exact="Some text", body_text="only one")
    code, out, _ = _run_cli("list", str(tmp_doc))
    assert code == 0
    assert "message" not in out.split("\n")[0]


def test_cli_list_context_flag(tmp_doc):
    """--context controls surrounding line count."""
    append_comment(tmp_doc, exact="Some text", body_text="hi")
    _, out_default, _ = _run_cli("list", str(tmp_doc))
    _, out_narrow, _ = _run_cli("list", str(tmp_doc), "--context", "0", "0")
    assert len(out_narrow) < len(out_default)


def test_cli_list_doc_position_sort(tmp_doc):
    """Anchored threads are sorted by document position, not creation order."""
    append_comment(tmp_doc, exact="Duplicate text here.", body_text="later in doc")
    append_comment(tmp_doc, exact="Some text", body_text="earlier in doc")
    code, out, _ = _run_cli("list", str(tmp_doc))
    assert code == 0
    pos_earlier = out.index("earlier in doc")
    pos_later = out.index("later in doc")
    assert pos_earlier < pos_later


def test_cli_show_has_status(tmp_doc):
    """show command always displays status."""
    ann = append_comment(tmp_doc, exact="Some text", body_text="hi")
    short_prefix = ann["id"].removeprefix("urn:uuid:")[:4]
    code, out, _ = _run_cli("show", str(tmp_doc), short_prefix)
    assert code == 0
    assert "[open]" in out


# ── locate_anchor context window ───────────────────────


def test_locate_anchor_default_context(tmp_doc):
    """Default context_before=2, context_after=2."""
    selector = {"exact": "Some text to anchor comments to."}
    ctx = locate_anchor(tmp_doc, selector)
    assert ctx["found"]
    # Anchor is at line 7 of an 11-line doc.
    # 2 before (lines 5-6) + anchor (line 7) + caret + 2 after (lines 8-9) = 6 items
    assert len(ctx["context_lines"]) == 6


def test_locate_anchor_custom_context(tmp_doc):
    """Custom context_before=0, context_after=0 shows only anchor line."""
    selector = {"exact": "Some text to anchor comments to."}
    ctx_narrow = locate_anchor(tmp_doc, selector, context_before=0, context_after=0)
    ctx_wide = locate_anchor(tmp_doc, selector, context_before=5, context_after=5)
    assert ctx_narrow["found"] and ctx_wide["found"]
    # Narrow should have fewer context lines than wide
    assert len(ctx_narrow["context_lines"]) < len(ctx_wide["context_lines"])


def test_locate_anchor_context_zero_zero(tmp_doc):
    """--context 0 0 still shows the anchor line itself."""
    selector = {"exact": "Some text to anchor comments to."}
    ctx = locate_anchor(tmp_doc, selector, context_before=0, context_after=0)
    assert ctx["found"]
    assert len(ctx["context_lines"]) >= 1  # at least anchor + caret


# ── CLI export ─────────────────────────────────────────


def test_cli_export_html(tmp_doc, tmp_path):
    """scholia export --to html produces a standalone HTML file."""
    out = tmp_path / "out.html"
    code, stdout, stderr = _run_cli("export", str(tmp_doc), "--to", "html", "-o", str(out))
    assert code == 0, f"stderr: {stderr}"
    assert out.exists()
    content = out.read_text()
    assert "<html" in content or "<!DOCTYPE" in content


def test_cli_export_latex(tmp_doc, tmp_path):
    """scholia export --to latex produces a .tex file."""
    out = tmp_path / "out.tex"
    code, stdout, stderr = _run_cli("export", str(tmp_doc), "--to", "latex", "-o", str(out))
    assert code == 0, f"stderr: {stderr}"
    assert out.exists()
    assert "\\begin{document}" in out.read_text()


def test_cli_export_default_output_name(tmp_doc):
    """Without -o, export writes <stem>.html in cwd."""
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "export", str(tmp_doc), "--to", "html"],
        capture_output=True, text=True, cwd=str(tmp_doc.parent),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    expected = tmp_doc.parent / "test.html"
    assert expected.exists()


def test_cli_export_missing_file():
    """Export of nonexistent file returns error."""
    code, _, stderr = _run_cli("export", "/nonexistent/doc.md", "--to", "html")
    assert code == 1


def test_cli_export_pdf_no_latex(tmp_doc, tmp_path):
    """PDF export without LaTeX engine shows clear error message."""
    import shutil
    # Only test if no LaTeX engine is available
    if shutil.which("xelatex") or shutil.which("tectonic") or shutil.which("lualatex") or shutil.which("pdflatex"):
        pytest.skip("LaTeX engine available; can't test missing-engine error")
    out = tmp_path / "out.pdf"
    code, _, stderr = _run_cli("export", str(tmp_doc), "--to", "pdf", "-o", str(out))
    assert code == 1
    assert "latex" in stderr.lower() or "pdf" in stderr.lower()
