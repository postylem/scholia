"""Integration tests for the scholia server."""

import pytest
import pytest_asyncio

from scholia.comments import append_comment, load_comments
from scholia.server import (
    ScholiaServer,
    _build_pandoc_base_cmd,
    _render_export_sync,
    _render_pandoc_sync,
)
from scholia.state import load_state

# ── Pandoc rendering tests ────────────────────────────


def test_render_pandoc_sync_basic(tmp_doc):
    """Pandoc renders markdown to HTML fragment with expected structure."""
    html, _stderr = _render_pandoc_sync(tmp_doc)
    assert "<p>Some text to anchor comments to.</p>" in html
    assert "Test Document" in html  # title from frontmatter


def test_render_pandoc_sync_with_math(tmp_path):
    """Math expressions produce KaTeX-compatible markup."""
    doc = tmp_path / "math.md"
    doc.write_text("---\ntitle: Math\n---\n\nInline $x^2$ and display:\n\n$$E = mc^2$$\n")
    html, _stderr = _render_pandoc_sync(doc)
    assert "x^2" in html
    assert "E = mc^2" in html


def test_render_pandoc_sync_number_sections(tmp_path):
    """number-sections frontmatter adds section numbers."""
    doc = tmp_path / "numbered.md"
    doc.write_text("---\ntitle: Numbered\nnumber-sections: true\n---\n\n# First\n\n## Sub\n")
    html, _stderr = _render_pandoc_sync(doc)
    assert "header-section-number" in html or 'data-number="1"' in html


def test_render_pandoc_sync_sidenotes(tmp_path):
    """Sidenote filter converts footnotes to Tufte-style sidenotes."""
    doc = tmp_path / "notes.md"
    doc.write_text(
        "---\ntitle: Notes\n---\n\n" "Some text with a note.[^1]\n\n" "[^1]: This is a sidenote.\n"
    )
    html, _stderr = _render_pandoc_sync(doc, sidenotes=True)
    assert "sidenote-wrapper" in html
    assert "sidenote-number" in html
    assert "margin-toggle" in html
    assert "This is a sidenote." in html


def test_render_pandoc_sync_margin_note(tmp_path):
    """Margin notes use {-} prefix and produce marginnote class."""
    doc = tmp_path / "margin.md"
    doc.write_text(
        "---\ntitle: Margin\n---\n\n"
        "Text with margin note.[^1]\n\n"
        "[^1]: {-} This is a margin note.\n"
    )
    html, _stderr = _render_pandoc_sync(doc, sidenotes=True)
    assert "marginnote" in html
    assert "This is a margin note." in html


def test_render_pandoc_sync_block_sidenote(tmp_path):
    """Block sidenotes {^} preserve block content in a div."""
    doc = tmp_path / "block.md"
    doc.write_text(
        "---\ntitle: Block\n---\n\n"
        "Text with block note.[^1]\n\n"
        "[^1]:\n    {^} Block note with a list:\n\n"
        "    - Item one\n    - Item two\n"
    )
    html, _stderr = _render_pandoc_sync(doc, sidenotes=True)
    assert '<div class="sidenote-wrapper">' in html
    assert "Item one" in html
    assert "Item two" in html


def test_render_pandoc_sync_footnote_passthrough(tmp_path):
    """Footnotes with {.} prefix remain as standard footnotes."""
    doc = tmp_path / "passthrough.md"
    doc.write_text(
        "---\ntitle: Passthrough\n---\n\n"
        "Text with real footnote.[^1]\n\n"
        "[^1]: {.} This stays a footnote.\n"
    )
    html, _stderr = _render_pandoc_sync(doc, sidenotes=True)
    # {.} footnotes are NOT converted to sidenotes
    assert "sidenote-wrapper" not in html
    # Content appears as a regular Pandoc footnote
    assert "This stays a footnote." in html


def test_render_pandoc_sync_strips_markers_in_endnote_mode(tmp_path):
    """Sidenote markers are stripped when rendering without the filter."""
    doc = tmp_path / "markers.md"
    doc.write_text(
        "---\ntitle: Markers\n---\n\n"
        "A[^1] B[^2] C[^3] D[^4]\n\n"
        "[^1]: {^} Block sidenote text.\n\n"
        "[^2]: {-} Margin note text.\n\n"
        "[^3]: {.} Footnote text.\n\n"
        "[^4]: {^-} Block margin text.\n"
    )
    html, _stderr = _render_pandoc_sync(doc, sidenotes=False)
    assert "Block sidenote text." in html
    assert "Margin note text." in html
    assert "Footnote text." in html
    assert "Block margin text." in html
    # Markers should NOT appear as literal text
    assert "{^}" not in html
    assert "{-}" not in html
    assert "{.}" not in html
    assert "{^-}" not in html


# ── _build_pandoc_base_cmd tests ──────────────────────


def test_build_pandoc_base_cmd_basic(tmp_doc):
    """Base command includes citeproc, from-format, and csl."""
    cmd, md_text = _build_pandoc_base_cmd(tmp_doc)
    assert "pandoc" in cmd
    assert "--citeproc" in cmd
    assert "--from=markdown+tex_math_single_backslash" in cmd
    assert "--metadata=link-citations:true" in cmd
    # Should NOT include HTML-specific flags
    assert "--katex" not in cmd
    assert "--section-divs" not in cmd
    assert "--to=html5" not in cmd


def test_build_pandoc_base_cmd_number_sections(tmp_path):
    """number-sections frontmatter adds --number-sections."""
    doc = tmp_path / "numbered.md"
    doc.write_text("---\ntitle: T\nnumber-sections: true\n---\n\n# H1\n")
    cmd, _ = _build_pandoc_base_cmd(doc)
    assert "--number-sections" in cmd


def test_build_pandoc_base_cmd_macros(tmp_path):
    """macros: frontmatter injects macro content into markdown text."""
    macros = tmp_path / "macros.tex"
    macros.write_text(r"\newcommand{\foo}{bar}")
    doc = tmp_path / "doc.md"
    doc.write_text("---\ntitle: T\nmacros: macros.tex\n---\n\nHello\n")
    cmd, md_text = _build_pandoc_base_cmd(doc)
    assert r"\newcommand{\foo}{bar}" in md_text


@pytest.fixture
def server_app(tmp_doc):
    """Create a ScholiaServer app for testing."""
    server = ScholiaServer(str(tmp_doc))
    return server


@pytest_asyncio.fixture
async def client(aiohttp_client, server_app):
    return await aiohttp_client(server_app.app)


@pytest.mark.asyncio
async def test_index_returns_html(client):
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "scholia-sidebar" in text
    assert "__SCHOLIA_COMMENTS__" in text
    assert "__SCHOLIA_STATE__" in text


@pytest.mark.asyncio
async def test_index_uses_yaml_title(client):
    """Page <title> should come from YAML frontmatter."""
    resp = await client.get("/")
    text = await resp.text()
    assert "<title>Test Document</title>" in text


@pytest.mark.asyncio
async def test_static_files(client):
    resp = await client.get("/static/scholia.js")
    assert resp.status == 200


@pytest.mark.asyncio
async def test_ws_new_comment(client, tmp_doc):
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(tmp_doc.resolve())})
    await ws.send_json(
        {
            "type": "new_comment",
            "exact": "Some text",
            "prefix": "",
            "suffix": "",
            "body": "test comment",
        }
    )
    await ws.close()
    comments = load_comments(tmp_doc)
    assert len(comments) == 1
    assert comments[0]["body"][0]["value"] == "test comment"


@pytest.mark.asyncio
async def test_ws_reply(client, tmp_doc):
    ann = append_comment(tmp_doc, exact="Some text", body_text="hi")
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(tmp_doc.resolve())})
    await ws.send_json(
        {
            "type": "reply",
            "annotation_id": ann["id"],
            "body": "reply text",
            "creator": "human",
        }
    )
    await ws.close()
    comments = load_comments(tmp_doc)
    assert len(comments[0]["body"]) == 2


@pytest.mark.asyncio
async def test_ws_resolve(client, tmp_doc):
    ann = append_comment(tmp_doc, exact="Some text", body_text="hi")
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(tmp_doc.resolve())})
    await ws.send_json(
        {
            "type": "resolve",
            "annotation_id": ann["id"],
        }
    )
    await ws.close()
    comments = load_comments(tmp_doc)
    assert comments[0]["scholia:status"] == "resolved"
    # Resolve should also mark as read
    state = load_state(tmp_doc)
    assert ann["id"] in state
    assert state[ann["id"]]["lastReadAt"] is not None


@pytest.mark.asyncio
async def test_ws_edit_body(client, tmp_doc):
    ann = append_comment(tmp_doc, exact="Some text", body_text="original")
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(tmp_doc.resolve())})
    await ws.send_json(
        {
            "type": "edit_body",
            "annotation_id": ann["id"],
            "body": "edited text",
        }
    )
    await ws.close()
    comments = load_comments(tmp_doc)
    assert comments[0]["body"][-1]["value"] == "edited text"


@pytest.mark.asyncio
async def test_ws_mark_read(client, tmp_doc):
    ann = append_comment(tmp_doc, exact="Some text", body_text="hi")
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(tmp_doc.resolve())})
    await ws.send_json(
        {
            "type": "mark_read",
            "annotation_id": ann["id"],
        }
    )
    await ws.close()
    state = load_state(tmp_doc)
    assert ann["id"] in state
    assert state[ann["id"]]["lastReadAt"] is not None


@pytest.mark.asyncio
async def test_ws_render_markdown(client, tmp_doc):
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(tmp_doc.resolve())})
    await ws.send_json(
        {
            "type": "render_markdown",
            "text": "**bold** and *italic*",
            "request_id": "req-1",
        }
    )
    msg = await ws.receive_json()
    assert msg["type"] == "rendered_markdown"
    assert msg["request_id"] == "req-1"
    assert "<strong>bold</strong>" in msg["html"]
    assert "<em>italic</em>" in msg["html"]
    await ws.close()


@pytest.mark.asyncio
async def test_ws_mark_unread(client, tmp_doc):
    ann = append_comment(tmp_doc, exact="Some text", body_text="hi")
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(tmp_doc.resolve())})
    await ws.send_json({"type": "mark_read", "annotation_id": ann["id"]})
    await ws.send_json({"type": "mark_unread", "annotation_id": ann["id"]})
    await ws.close()
    state = load_state(tmp_doc)
    assert state[ann["id"]]["lastReadAt"] is None


# ── Static analysis ──────────────────────────────────


# ── list-dir and _display_path tests ─────────────────


@pytest.mark.asyncio
async def test_list_dir_returns_sorted_entries(client, tmp_doc):
    """list-dir returns dirs first (sorted), then files (sorted), no dotfiles."""
    d = tmp_doc.parent
    (d / "subdir").mkdir()
    (d / "another.md").write_text("# Another")
    (d / "zebra.txt").write_text("txt")
    (d / ".hidden").write_text("secret")
    resp = await client.get("/api/list-dir", params={"path": str(d)})
    assert resp.status == 200
    data = await resp.json()
    names = [e["name"] for e in data["entries"]]
    assert names[0] == ".."
    assert ".hidden" not in names
    # dirs before files
    dir_names = [e["name"] for e in data["entries"] if e["type"] == "dir" and e["name"] != ".."]
    file_names = [e["name"] for e in data["entries"] if e["type"] == "file"]
    assert dir_names == sorted(dir_names)
    assert file_names == sorted(file_names)
    dir_idx = max(i for i, e in enumerate(data["entries"]) if e["type"] == "dir")
    file_idx = min(i for i, e in enumerate(data["entries"]) if e["type"] == "file")
    assert dir_idx < file_idx


@pytest.mark.asyncio
async def test_list_dir_symlinks(client, tmp_doc):
    """Symlinks include a 'link' field with the resolved target."""
    d = tmp_doc.parent
    target = d / "real.md"
    target.write_text("# Real")
    link = d / "linked.md"
    link.symlink_to(target)
    resp = await client.get("/api/list-dir", params={"path": str(d)})
    data = await resp.json()
    linked_entry = next(e for e in data["entries"] if e["name"] == "linked.md")
    assert linked_entry["type"] == "file"
    assert linked_entry["link"] == str(target.resolve())


@pytest.mark.asyncio
async def test_list_dir_bad_path(client):
    """Non-existent path returns error JSON."""
    resp = await client.get("/api/list-dir", params={"path": "/nonexistent/path"})
    assert resp.status == 200
    data = await resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_list_dir_empty(client, tmp_doc):
    """Empty directory returns only '..' entry."""
    d = tmp_doc.parent / "empty"
    d.mkdir()
    resp = await client.get("/api/list-dir", params={"path": str(d)})
    data = await resp.json()
    assert len(data["entries"]) == 1
    assert data["entries"][0]["name"] == ".."


def test_display_path_relative(tmp_doc, monkeypatch):
    """Files under launch_dir get relative display paths."""
    monkeypatch.chdir(tmp_doc.parent)
    server = ScholiaServer(str(tmp_doc))
    abs_path = tmp_doc.resolve()
    result = server._display_path(abs_path)
    # Should be relative (not start with /)
    assert not result.startswith("/")


def test_display_path_outside(tmp_doc, tmp_path):
    """Files outside launch_dir get absolute display paths."""
    server = ScholiaServer(str(tmp_doc))
    outside = tmp_path.parent / "elsewhere" / "doc.md"
    result = server._display_path(outside.resolve())
    assert result.startswith("/")


# ── ?file= routing tests ─────────────────────────────


@pytest.mark.asyncio
async def test_index_file_param(client, tmp_doc):
    """GET /?file=path renders the specified file."""
    other = tmp_doc.parent / "other.md"
    other.write_text("---\ntitle: Other Doc\n---\n\nOther content.\n")
    resp = await client.get("/", params={"file": str(other)})
    assert resp.status == 200
    text = await resp.text()
    assert "Other Doc" in text
    assert "Other content" in text


@pytest.mark.asyncio
async def test_index_file_not_found(client):
    """GET /?file=nonexistent returns error page, not 500."""
    resp = await client.get("/", params={"file": "/nonexistent/doc.md"})
    assert resp.status == 200
    text = await resp.text()
    assert "scholia-sidebar" in text  # still a valid page
    assert "not found" in text.lower() or "error" in text.lower()


@pytest.mark.asyncio
async def test_index_no_param_uses_default(client, tmp_doc):
    """GET / with no file param renders the default doc."""
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "Test Document" in text


@pytest.mark.asyncio
async def test_index_relative_file_param(client, tmp_doc, server_app, monkeypatch):
    """GET /?file=relative resolves relative to launch_dir."""
    other = tmp_doc.parent / "rel.md"
    other.write_text("---\ntitle: Relative\n---\n\nRelative content.\n")
    # Set launch_dir so relative path resolves correctly
    monkeypatch.setattr(server_app, "launch_dir", tmp_doc.parent.resolve())
    resp = await client.get("/", params={"file": "rel.md"})
    assert resp.status == 200
    text = await resp.text()
    assert "Relative" in text


@pytest.mark.asyncio
async def test_index_render_error(client, tmp_doc):
    """A file that causes Pandoc to fail shows an error page, not a 500."""
    bad = tmp_doc.parent / "bad.md"
    bad.write_text("---\nbibliography: /nonexistent/refs.bib\n---\n\n@cite_this\n")
    resp = await client.get("/", params={"file": str(bad)})
    assert resp.status == 200
    text = await resp.text()
    assert "scholia-sidebar" in text  # still a valid page
    assert "error" in text.lower()


# ── Per-file WebSocket tracking tests ─────────────────


@pytest.mark.asyncio
async def test_ws_watch_registers_file(client, tmp_doc):
    """WS client sending 'watch' is registered for that file."""
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(tmp_doc.resolve())})
    await ws.send_json(
        {
            "type": "new_comment",
            "exact": "Some text",
            "prefix": "",
            "suffix": "",
            "body": "after watch",
        }
    )
    await ws.close()
    comments = load_comments(tmp_doc)
    assert len(comments) == 1
    assert comments[0]["body"][0]["value"] == "after watch"


@pytest.mark.asyncio
async def test_ws_operations_use_watched_file(client, tmp_doc):
    """WS operations target the watched file, not the default doc."""
    other = tmp_doc.parent / "other.md"
    other.write_text("---\ntitle: Other\n---\n\nOther text.\n")
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(other.resolve())})
    await ws.send_json(
        {
            "type": "new_comment",
            "exact": "Other text",
            "prefix": "",
            "suffix": "",
            "body": "comment on other",
        }
    )
    await ws.close()
    from scholia.comments import load_comments

    assert len(load_comments(other)) == 1
    assert len(load_comments(tmp_doc)) == 0


# ── Full navigation flow ──────────────────────────────


@pytest.mark.asyncio
async def test_full_navigation_flow(client, tmp_doc):
    """Full flow: load default → list dir → navigate to other file."""
    # Create another file
    other = tmp_doc.parent / "other.md"
    other.write_text("---\ntitle: Other\n---\n\nOther content.\n")

    # Load default page
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "Test Document" in text

    # List directory
    resp = await client.get("/api/list-dir", params={"path": str(tmp_doc.parent)})
    data = await resp.json()
    file_names = [e["name"] for e in data["entries"] if e["type"] == "file"]
    assert "other.md" in file_names

    # Navigate to other file
    resp = await client.get("/", params={"file": str(other)})
    assert resp.status == 200
    text = await resp.text()
    assert "Other" in text

    # WS works on the new file
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(other.resolve())})
    await ws.send_json(
        {
            "type": "new_comment",
            "exact": "Other content",
            "prefix": "",
            "suffix": "",
            "body": "comment on other",
        }
    )
    await ws.close()
    assert len(load_comments(other)) == 1


# ── Export endpoint tests ─────────────────────────────


@pytest.mark.asyncio
async def test_export_pdf_endpoint_html_fallback(client, tmp_doc):
    """When no LaTeX engine, export-pdf returns fallback error."""
    resp = await client.get("/api/export-pdf", params={"file": str(tmp_doc)})
    # If LaTeX is available, we get a PDF; if not, we get a fallback JSON error.
    if resp.status == 200:
        assert resp.content_type == "application/pdf"
        data = await resp.read()
        assert len(data) > 0
    else:
        assert resp.status == 422
        data = await resp.json()
        assert "fallback" in data


@pytest.mark.asyncio
async def test_export_pdf_endpoint_missing_file(client):
    """Export of nonexistent file returns 404."""
    resp = await client.get("/api/export-pdf", params={"file": "/nonexistent/doc.md"})
    assert resp.status == 404


# ── _render_export_sync tests ─────────────────────────


def test_render_export_html(tmp_doc, tmp_path):
    """Export to standalone HTML produces valid HTML file."""
    out = tmp_path / "out.html"
    _render_export_sync(tmp_doc, "html", out)
    content = out.read_text()
    assert "<!DOCTYPE" in content or "<html" in content
    assert "Test Document" in content


def test_render_export_latex(tmp_doc, tmp_path):
    """Export to LaTeX produces valid .tex file."""
    out = tmp_path / "out.tex"
    _render_export_sync(tmp_doc, "latex", out)
    content = out.read_text()
    assert "\\begin{document}" in content


def test_render_export_returns_bytes(tmp_doc):
    """When output_path is None, returns bytes."""
    data = _render_export_sync(tmp_doc, "html")
    assert isinstance(data, bytes)
    assert b"<html" in data or b"<!DOCTYPE" in data


@pytest.mark.asyncio
async def test_relocate_endpoint(aiohttp_client, tmp_path):
    """POST /api/relocate moves document and updates server."""
    doc = tmp_path / "src.md"
    doc.write_text("# Hello")
    jsonl = tmp_path / "src.md.scholia.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    dest = tmp_path / "dest.md"

    server = ScholiaServer(str(doc))
    client = await aiohttp_client(server.app)

    resp = await client.post("/api/relocate", json={"to": str(dest)})
    assert resp.status == 200
    data = await resp.json()
    assert "dest.md" in data["path"]
    assert dest.exists()
    assert not doc.exists()
    assert (tmp_path / "dest.md.scholia.jsonl").exists()


@pytest.mark.asyncio
async def test_ws_save_as(aiohttp_client, tmp_path):
    """WebSocket save_as message triggers relocate."""
    doc = tmp_path / "src.md"
    doc.write_text("# Hello")
    dest = tmp_path / "saved.md"

    server = ScholiaServer(str(doc))
    client = await aiohttp_client(server.app)

    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(doc)})

    await ws.send_json({"type": "save_as", "path": str(dest)})
    msg = await ws.receive_json()
    assert msg["type"] == "relocated"
    assert "saved.md" in msg["path"]
    assert dest.exists()
    assert not doc.exists()

    await ws.close()


def test_server_writes_and_clears_server_state(tmp_path):
    """Server writes _server to state on start, clears on exit."""
    from scholia.state import get_server

    doc = tmp_path / "test.md"
    doc.write_text("# Hello")
    assert get_server(str(doc)) is None
    server = ScholiaServer(str(doc))
    server._register_server_state(8088)
    info = get_server(str(doc))
    assert info is not None
    assert info["port"] == 8088
    assert "pid" in info
    server._clear_server_state()
    assert get_server(str(doc)) is None
