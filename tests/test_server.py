"""Integration tests for the scholia server."""

import asyncio
import shutil

import pytest
import pytest_asyncio

from scholia.comments import append_comment, load_comments
from scholia.server import (
    ScholiaServer,
    _build_pandoc_base_cmd,
    _default_pdf_engine,
    _has_latex_engine,
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
        "---\ntitle: Notes\n---\n\nSome text with a note.[^1]\n\n[^1]: This is a sidenote.\n"
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


def test_render_pandoc_sync_rewrites_image_src(tmp_path):
    """Relative image src is rewritten to the /doc-assets/ route.

    The page is served at ``/``, so a bare relative ``src="image.png"``
    resolves to ``/image.png`` and 404s. Rewriting to ``/doc-assets/``
    (which knows the document's directory) lets the browser fetch it.
    """
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\n![cap](image.png)\n")
    html, _stderr = _render_pandoc_sync(doc)
    assert 'src="image.png"' not in html
    assert "/doc-assets/image.png?base=" in html


def test_render_pandoc_sync_keeps_remote_and_absolute_src(tmp_path):
    """Remote URLs, data URIs, and absolute/anchor paths are left untouched."""
    doc = tmp_path / "doc.md"
    doc.write_text("# T\n\n![a](https://example.com/x.png)\n\n![b](/already/absolute.png)\n")
    html, _stderr = _render_pandoc_sync(doc)
    assert 'src="https://example.com/x.png"' in html
    assert 'src="/already/absolute.png"' in html
    assert "/doc-assets/" not in html


# ── Quarto asset rewriting ────────────────────────────


def test_rewrite_quarto_assets(tmp_path):
    """Quarto rewrite: <stem>_files/ → /quarto-assets/, static relative
    images → /doc-assets/, while CDN/absolute URLs and links stay put."""
    from scholia.server import _rewrite_quarto_assets

    html = (
        '<link href="report_files/libs/bootstrap.css">'
        '<script src="report_files/libs/quarto.js"></script>'
        '<script src="https://cdn.example.com/mathjax.js"></script>'
        '<img src="images/pipeline.png" alt="x" />'
        '<a href="notes.md">link</a>'
    )
    out = _rewrite_quarto_assets(html, "report", tmp_path)
    # Quarto's own _files/ assets go through /quarto-assets/.
    assert "report_files/" not in out
    assert 'href="/quarto-assets/libs/bootstrap.css"' in out
    assert 'src="/quarto-assets/libs/quarto.js"' in out
    # Static markdown images go through /doc-assets/.
    assert "/doc-assets/images/pipeline.png?base=" in out
    assert 'src="images/pipeline.png"' not in out
    # CDN scripts and local links are left untouched.
    assert 'src="https://cdn.example.com/mathjax.js"' in out
    assert 'href="notes.md"' in out


@pytest.mark.skipif(not shutil.which("quarto"), reason="quarto not installed")
def test_render_quarto_sync_rewrites_static_image(tmp_path):
    """A real Quarto render rewrites static markdown images to /doc-assets/."""
    from scholia.server import _render_quarto_sync

    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    doc = tmp_path / "doc.qmd"
    doc.write_text("---\ntitle: Q\nformat: html\n---\n\n![cap](images/pic.png)\n")
    html, _stderr = _render_quarto_sync(doc, use_defaults=False)
    assert "/doc-assets/images/pic.png?base=" in html
    assert 'src="images/pic.png"' not in html


@pytest.mark.skipif(not shutil.which("quarto"), reason="quarto not installed")
def test_render_quarto_sync_applies_macros(tmp_path):
    """macros: frontmatter expands LaTeX macros in a Quarto document's math.

    Pandoc (used under the hood by Quarto) expands ``\\newcommand`` definitions
    placed in the body at parse time, so the macro must resolve in the math —
    the unexpanded command must not survive, and the temp file/_files
    byproducts of the macro injection must be cleaned up."""
    from scholia.server import _render_quarto_sync

    (tmp_path / "macros.tex").write_text(
        r"\newcommand{\KL}[2]{D_{\mathrm{KL}}\!\left(#1 \,\|\, #2\right)}" + "\n"
    )
    doc = tmp_path / "doc.qmd"
    doc.write_text(
        "---\ntitle: Q\nformat: html\nmacros: macros.tex\n---\n\n"
        "The divergence $\\KL{p}{q}$ appears here.\n"
    )
    html, _stderr = _render_quarto_sync(doc, use_defaults=False)
    # Macro expanded server-side; the undefined command must not survive.
    assert "D_{\\mathrm{KL}}" in html
    assert "\\KL{p}{q}" not in html
    # No literal definition leaked into the body.
    assert "newcommand" not in html
    # Temp render byproducts cleaned up; original source untouched.
    assert not [p for p in tmp_path.iterdir() if "scholia-macros" in p.name]
    assert "macros: macros.tex" in doc.read_text()


@pytest.mark.skipif(not shutil.which("quarto"), reason="quarto not installed")
def test_render_quarto_export_sync_applies_macros(tmp_path):
    """macros: frontmatter expands LaTeX macros when exporting a Quarto doc."""
    from scholia.server import _render_quarto_export_sync

    (tmp_path / "macros.tex").write_text(
        r"\newcommand{\KL}[2]{D_{\mathrm{KL}}\!\left(#1 \,\|\, #2\right)}" + "\n"
    )
    doc = tmp_path / "doc.qmd"
    doc.write_text(
        "---\ntitle: Q\nformat: html\nmacros: macros.tex\n---\n\n"
        "The divergence $\\KL{p}{q}$ appears here.\n"
    )
    out = _render_quarto_export_sync(doc, "html").decode()
    assert "D_{\\mathrm{KL}}" in out
    assert "\\KL{p}{q}" not in out
    # Temp render byproducts cleaned up; original source untouched.
    assert not [p for p in tmp_path.iterdir() if "scholia-macros" in p.name]
    assert "macros: macros.tex" in doc.read_text()


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


def test_build_pandoc_base_cmd_macros_strips_latex_comments(tmp_path):
    """macros: LaTeX % comments in macros file must not leak into markdown body."""
    macros = tmp_path / "macros.tex"
    macros.write_text(
        "% --- General probability macros ---\n"
        r"\newcommand{\statespace}{\mathcal{X}}"
        "\n"
        "% --- Language-model-specific ---\n"
        r"\newcommand{\vocab}{\Sigma}"
        "  % inline trailing comment\n"
        r"\newcommand{\pct}{10\%}"
        "\n"
    )
    doc = tmp_path / "doc.md"
    doc.write_text("---\ntitle: T\nmacros: macros.tex\n---\n\nHello\n")
    _, md_text = _build_pandoc_base_cmd(doc)
    assert "General probability macros" not in md_text
    assert "Language-model-specific" not in md_text
    assert "inline trailing comment" not in md_text
    assert r"\newcommand{\statespace}{\mathcal{X}}" in md_text
    assert r"\newcommand{\vocab}{\Sigma}" in md_text
    # Escaped percent (\%) must be preserved as a literal, not treated as comment.
    assert r"\newcommand{\pct}{10\%}" in md_text


# ── _inject_macros (shared by Pandoc + Quarto paths) ──


def test_inject_macros_splices_into_body_after_frontmatter(tmp_path):
    """macros: frontmatter splices macro content into the body, right after
    the YAML frontmatter — works regardless of file extension (.md or .qmd)."""
    from scholia.server import _inject_macros

    macros = tmp_path / "macros.tex"
    macros.write_text(r"\newcommand{\foo}{bar}")
    doc = tmp_path / "doc.qmd"
    doc.write_text("---\ntitle: T\nmacros: macros.tex\n---\n\nHello\n")
    out = _inject_macros(doc.read_text(), doc)
    assert r"\newcommand{\foo}{bar}" in out
    # spliced after the frontmatter and before the body text
    assert out.index("title: T") < out.index(r"\newcommand{\foo}{bar}") < out.index("Hello")


def test_inject_macros_noop_without_macros_key(tmp_path):
    """No macros: key → text returned unchanged."""
    from scholia.server import _inject_macros

    doc = tmp_path / "doc.qmd"
    text = "---\ntitle: T\n---\n\nHello\n"
    doc.write_text(text)
    assert _inject_macros(text, doc) == text


def test_macro_injected_source_is_not_a_dotfile(tmp_path):
    """The temp render source must not be hidden: LaTeX runs with
    ``openout_any=p`` and refuses to write .log/.aux/.pdf for a dot-prefixed
    basename, which breaks Quarto PDF export."""
    from scholia.server import _write_macro_injected_source

    (tmp_path / "macros.tex").write_text(r"\newcommand{\foo}{bar}")
    doc = tmp_path / "doc.qmd"
    doc.write_text("---\ntitle: T\nmacros: macros.tex\n---\n\nHello\n")
    tmp = _write_macro_injected_source(doc)
    try:
        assert tmp is not None
        assert not tmp.name.startswith("."), f"temp source is hidden: {tmp.name}"
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


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
async def test_doc_assets_serves_local_file(client, tmp_doc):
    """/doc-assets/ serves files from the document's directory."""
    from urllib.parse import quote

    img = tmp_doc.parent / "pic.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nDATA")
    base = quote(str(tmp_doc.parent.resolve()), safe="")
    resp = await client.get(f"/doc-assets/pic.png?base={base}")
    assert resp.status == 200
    assert await resp.read() == b"\x89PNG\r\n\x1a\nDATA"


@pytest.mark.asyncio
async def test_doc_assets_missing_file_404(client, tmp_doc):
    from urllib.parse import quote

    base = quote(str(tmp_doc.parent.resolve()), safe="")
    resp = await client.get(f"/doc-assets/nope.png?base={base}")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_doc_assets_blocks_traversal(client, tmp_doc):
    """A path escaping the base directory is rejected (no path traversal)."""
    from urllib.parse import quote

    # Secret outside the document directory.
    secret = tmp_doc.parent.parent / "secret.txt"
    secret.write_text("top secret")
    base = quote(str(tmp_doc.parent.resolve()), safe="")
    # %2e%2e%2f == "../" — encoded so the test client doesn't normalise it away.
    resp = await client.get(f"/doc-assets/%2e%2e%2fsecret.txt?base={base}")
    assert resp.status in (403, 404)


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


@pytest.mark.skipif(not _has_latex_engine(), reason="needs a LaTeX engine")
@pytest.mark.asyncio
async def test_export_pdf_compile_error_is_not_print_fallback(aiohttp_client, tmp_path):
    """A genuine LaTeX compile failure (engine present) must surface the real
    error, NOT silently downgrade to the browser-print fallback.

    Regression: the fallback used to fire for any stderr containing
    'latex'/'pdf', which matches every compile error.
    """
    doc = tmp_path / "broken.md"
    # Raw LaTeX that any engine rejects: undefined control sequence.
    doc.write_text(
        "---\ntitle: Broken\n---\n\n" "```{=latex}\n\\thiscommanddoesnotexistxyz\n```\n"
    )
    server = ScholiaServer(str(doc))
    client = await aiohttp_client(server.app)
    resp = await client.get("/api/export-pdf", params={"file": str(doc)})
    assert resp.status == 500
    data = await resp.json()
    assert "fallback" not in data
    assert "error" in data


@pytest.mark.skipif(not shutil.which("xelatex"), reason="needs xelatex")
def test_render_export_pdf_unicode(tmp_path):
    """A document with non-ASCII characters (e.g. ⇒) must export to PDF.

    Regression: pandoc defaulted to pdflatex, which errors on Unicode like
    ⇒ (U+21D2). scholia should select a Unicode-capable engine by default.
    """
    doc = tmp_path / "unicode.md"
    doc.write_text("---\ntitle: Unicode\n---\n\nMore samples ⇒ better estimate.\n")
    data = _render_export_sync(doc, "pdf")
    assert isinstance(data, bytes)
    assert data[:4] == b"%PDF"


@pytest.mark.skipif(not shutil.which("xelatex"), reason="needs xelatex")
def test_default_pdf_engine_prefers_unicode_capable(monkeypatch):
    """When xelatex is installed it is preferred over pdflatex."""
    monkeypatch.delenv("SCHOLIA_PDF_ENGINE", raising=False)
    assert _default_pdf_engine() in ("xelatex", "lualatex", "tectonic")


def test_default_pdf_engine_env_override(monkeypatch):
    """SCHOLIA_PDF_ENGINE overrides auto-detection."""
    monkeypatch.setenv("SCHOLIA_PDF_ENGINE", "tectonic")
    assert _default_pdf_engine() == "tectonic"
    monkeypatch.setenv("SCHOLIA_PDF_ENGINE", "  ")  # blank is ignored
    assert _default_pdf_engine() != ""


def test_export_pdf_command_honors_env_engine_and_colorlinks(tmp_doc, monkeypatch):
    """The pdf export command uses SCHOLIA_PDF_ENGINE and enables colorlinks
    (without running a real LaTeX engine)."""

    class FakeResult:
        returncode = 0
        stdout = b"%PDF-1.5 fake"
        stderr = b""

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeResult()

    monkeypatch.setenv("SCHOLIA_PDF_ENGINE", "lualatex")
    monkeypatch.setattr("scholia.server.subprocess.run", fake_run)
    out = _render_export_sync(tmp_doc, "pdf")
    assert out == b"%PDF-1.5 fake"
    cmd = captured["cmd"]
    assert "--pdf-engine=lualatex" in cmd
    assert "-V" in cmd
    assert "colorlinks=true" in cmd


def test_export_explicit_engine_beats_env(tmp_doc, monkeypatch):
    """An explicit pdf_engine argument takes precedence over the env var."""

    class FakeResult:
        returncode = 0
        stdout = b"%PDF"
        stderr = b""

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeResult()

    monkeypatch.setenv("SCHOLIA_PDF_ENGINE", "lualatex")
    monkeypatch.setattr("scholia.server.subprocess.run", fake_run)
    _render_export_sync(tmp_doc, "pdf", pdf_engine="tectonic")
    assert "--pdf-engine=tectonic" in captured["cmd"]


def test_render_export_latex_enables_colorlinks(tmp_doc, tmp_path):
    """LaTeX/PDF export enables colorlinks so citation/link text is visible.

    Without it, pandoc's default hyperref setup uses `hidelinks`, leaving
    citations clickable but rendered as plain black text.
    """
    out = tmp_path / "out.tex"
    _render_export_sync(tmp_doc, "latex", out)
    assert "colorlinks=true" in out.read_text()


def test_render_export_latex_respects_own_colorlinks(tmp_path):
    """A document that sets colorlinks itself is not overridden."""
    doc = tmp_path / "cl.md"
    doc.write_text("---\ntitle: T\ncolorlinks: false\n---\n\nhi\n")
    out = tmp_path / "out.tex"
    _render_export_sync(doc, "latex", out)
    assert "colorlinks=true" not in out.read_text()


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


# ── Review session endpoints (human → AI handshake) ──────────


@pytest.mark.asyncio
async def test_review_start_returns_session(client, tmp_doc):
    resp = await client.post(
        "/api/review/start", json={"doc": str(tmp_doc.resolve()), "instruction": "check it"}
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["session_id"].startswith("rev-")
    assert data["status"] == "waiting"
    assert data["instruction"] == "check it"


@pytest.mark.asyncio
async def test_review_start_dedups_active_session(client, tmp_doc):
    """A second start for the same document rejoins the first session."""
    r1 = await client.post("/api/review/start", json={"doc": str(tmp_doc.resolve())})
    r2 = await client.post("/api/review/start", json={"doc": str(tmp_doc.resolve())})
    assert (await r1.json())["session_id"] == (await r2.json())["session_id"]


@pytest.mark.asyncio
async def test_review_wait_pending_on_timeout(client, tmp_doc):
    r = await client.post("/api/review/start", json={"doc": str(tmp_doc.resolve())})
    sid = (await r.json())["session_id"]
    resp = await client.get("/api/review/wait", params={"session_id": sid, "timeout": "0.05"})
    data = await resp.json()
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_review_wait_unknown_session(client):
    resp = await client.get(
        "/api/review/wait", params={"session_id": "rev-nope", "timeout": "0.05"}
    )
    assert resp.status == 404
    assert (await resp.json())["status"] == "unknown"


@pytest.mark.asyncio
async def test_review_wait_resolves_on_ws_submit(client, tmp_doc):
    """The agent's long-poll unblocks when the browser submits a batch."""
    ann = append_comment(tmp_doc, exact="Some text", body_text="hi")
    r = await client.post("/api/review/start", json={"doc": str(tmp_doc.resolve())})
    sid = (await r.json())["session_id"]

    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(tmp_doc.resolve())})

    wait_task = asyncio.ensure_future(
        client.get("/api/review/wait", params={"session_id": sid, "timeout": "5"})
    )
    await asyncio.sleep(0.05)
    await ws.send_json(
        {
            "type": "review_submit",
            "session_id": sid,
            "comment_ids": [ann["id"]],
            "instruction": "please address",
            "final": False,
        }
    )
    resp = await wait_task
    data = await resp.json()
    await ws.close()
    assert data["status"] == "submitted"
    assert data["action"] == "submit"
    assert data["comment_ids"] == [ann["id"]]
    assert data["instruction"] == "please address"


@pytest.mark.asyncio
async def test_review_finish_ends_session(client, tmp_doc):
    r = await client.post("/api/review/start", json={"doc": str(tmp_doc.resolve())})
    sid = (await r.json())["session_id"]
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(tmp_doc.resolve())})
    wait_task = asyncio.ensure_future(
        client.get("/api/review/wait", params={"session_id": sid, "timeout": "5"})
    )
    await asyncio.sleep(0.05)
    await ws.send_json(
        {"type": "review_submit", "session_id": sid, "comment_ids": [], "final": True}
    )
    data = await (await wait_task).json()
    await ws.close()
    assert data["status"] == "submitted"
    assert data["action"] == "finish"
    # Session is gone after a finish — a re-poll finds nothing.
    resp = await client.get("/api/review/wait", params={"session_id": sid, "timeout": "0.05"})
    assert resp.status == 404


@pytest.mark.asyncio
async def test_review_start_recovers_stranded_finish_batch(client, tmp_doc):
    """If 'Send & finish' lands before the agent re-polls, the re-issued
    request_review rejoins the finished session and still receives the final
    batch — rather than opening a fresh empty session and stranding it."""
    ann = append_comment(tmp_doc, exact="Some text", body_text="last one")
    r1 = await client.post("/api/review/start", json={"doc": str(tmp_doc.resolve())})
    sid1 = (await r1.json())["session_id"]

    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(tmp_doc.resolve())})
    # Human clicks Send & finish while the agent is between rounds (not polling).
    await ws.send_json(
        {"type": "review_submit", "session_id": sid1, "comment_ids": [ann["id"]], "final": True}
    )
    await asyncio.sleep(0.1)

    # Agent re-issues request_review for the next round.
    r2 = await client.post("/api/review/start", json={"doc": str(tmp_doc.resolve())})
    sid2 = (await r2.json())["session_id"]
    assert sid2 == sid1, "re-request opened a new session; finish batch stranded"

    # ...and the agent's wait now delivers the stranded final batch.
    resp = await client.get("/api/review/wait", params={"session_id": sid2, "timeout": "2"})
    data = await resp.json()
    await ws.close()
    assert data["status"] == "submitted"
    assert data["action"] == "finish"
    assert data["comment_ids"] == [ann["id"]]


@pytest.mark.asyncio
async def test_review_cancel_aborts_wait(client, tmp_doc):
    r = await client.post("/api/review/start", json={"doc": str(tmp_doc.resolve())})
    sid = (await r.json())["session_id"]
    wait_task = asyncio.ensure_future(
        client.get("/api/review/wait", params={"session_id": sid, "timeout": "5"})
    )
    await asyncio.sleep(0.05)
    await client.post("/api/review/cancel", json={"session_id": sid})
    data = await (await wait_task).json()
    assert data["status"] == "aborted"


@pytest.mark.asyncio
async def test_review_wait_coalesces_queued_batches(client, tmp_doc):
    """A burst of per-comment sends reaches the agent in one batch, not one per poll."""
    r = await client.post("/api/review/start", json={"doc": str(tmp_doc.resolve())})
    sid = (await r.json())["session_id"]
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(tmp_doc.resolve())})
    await ws.send_json(
        {"type": "review_submit", "session_id": sid, "comment_ids": ["a"], "final": False}
    )
    await ws.send_json(
        {"type": "review_submit", "session_id": sid, "comment_ids": ["b"], "final": False}
    )
    await asyncio.sleep(0.1)  # let both submissions queue
    resp = await client.get("/api/review/wait", params={"session_id": sid, "timeout": "2"})
    data = await resp.json()
    await ws.close()
    assert data["status"] == "submitted"
    assert set(data["comment_ids"]) == {"a", "b"}


@pytest.mark.asyncio
async def test_watch_receives_review_state(client, tmp_doc):
    """A browser connecting mid-review is told about the active session."""
    r = await client.post(
        "/api/review/start", json={"doc": str(tmp_doc.resolve()), "instruction": "x"}
    )
    sid = (await r.json())["session_id"]
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(tmp_doc.resolve())})
    found = None
    for _ in range(10):
        msg = await asyncio.wait_for(ws.receive_json(), timeout=2)
        if msg.get("type") == "review_state":
            found = msg
            break
    await ws.close()
    assert found is not None
    assert any(s["session_id"] == sid for s in found["sessions"])
