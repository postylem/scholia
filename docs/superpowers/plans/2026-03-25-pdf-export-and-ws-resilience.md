# PDF Export & WebSocket Connection Resilience — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-format Pandoc export (PDF/HTML/LaTeX) with CLI and browser UI, and improve WebSocket reconnection with exponential backoff and a disconnect banner.

**Architecture:** Extract shared Pandoc command construction from `_render_pandoc_sync()`, add export functions and `/api/export-pdf` endpoint. Enhance frontend `connectWS()` with backoff and a non-blocking disconnect indicator.

**Tech Stack:** Python/aiohttp (server), Pandoc (rendering), vanilla JS (frontend), pytest + pytest-asyncio (tests)

**Spec:** `docs/superpowers/specs/2026-03-25-pdf-export-and-ws-resilience-design.md`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `scholia/server.py` | Extract `_build_pandoc_base_cmd()`, add `_render_export_sync()` / `render_export()`, add `/api/export-pdf` route |
| `scholia/cli.py` | Add `export` subcommand with `--to`, `--output`, `--pdf-engine` flags |
| `scholia/static/scholia.js` | Add Export PDF button in Options menu, WS backoff logic, disconnect banner |
| `scholia/static/scholia.css` | Disconnect banner styles |
| `tests/test_server.py` | Tests for export endpoint and base command extraction |
| `tests/test_core.py` | Tests for CLI export subcommand |

---

### Task 1: Extract `_build_pandoc_base_cmd()` from `_render_pandoc_sync()`

**Files:**
- Modify: `scholia/server.py:53-107`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write regression test for existing HTML rendering**

This test captures the current behavior before the refactor. It verifies that after we extract the shared command, `_render_pandoc_sync()` still produces identical output.

Add to `tests/test_server.py`:

```python
from scholia.server import _render_pandoc_sync


def test_render_pandoc_sync_basic(tmp_doc):
    """Pandoc renders markdown to HTML fragment with expected structure."""
    html = _render_pandoc_sync(tmp_doc)
    assert "<p>Some text to anchor comments to.</p>" in html
    assert "Test Document" in html  # title from frontmatter


def test_render_pandoc_sync_with_math(tmp_path):
    """Math expressions produce KaTeX-compatible markup."""
    doc = tmp_path / "math.md"
    doc.write_text("---\ntitle: Math\n---\n\nInline $x^2$ and display:\n\n$$E = mc^2$$\n")
    html = _render_pandoc_sync(doc)
    assert "x^2" in html
    assert "E = mc^2" in html


def test_render_pandoc_sync_number_sections(tmp_path):
    """number-sections frontmatter adds section numbers."""
    doc = tmp_path / "numbered.md"
    doc.write_text("---\ntitle: Numbered\nnumber-sections: true\n---\n\n# First\n\n## Sub\n")
    html = _render_pandoc_sync(doc)
    assert "header-section-number" in html or 'data-number="1"' in html
```

- [ ] **Step 2: Run tests to verify they pass with current code**

Run: `uv run pytest tests/test_server.py::test_render_pandoc_sync_basic tests/test_server.py::test_render_pandoc_sync_with_math tests/test_server.py::test_render_pandoc_sync_number_sections -v`
Expected: All PASS (these test existing behavior)

- [ ] **Step 3: Extract `_build_pandoc_base_cmd()`**

In `scholia/server.py`, add a new function before `_render_pandoc_sync` and refactor `_render_pandoc_sync` to use it.

New function (insert after `_has_footnotes`, around line 51):

```python
def _build_pandoc_base_cmd(doc_path: Path) -> tuple[list[str], str]:
    """Build format-agnostic Pandoc args and return (cmd, processed_md_text).

    Handles: crossref (if available), citeproc, bibliography/csl resolution,
    macros injection, number-sections, link-citations, input format.

    Does NOT include format-specific flags:
    - --katex (HTML-only; LaTeX/PDF handle math natively)
    - --section-divs (HTML-only)
    - --syntax-highlighting (caller decides)
    - --template / --standalone (format-specific)
    - --lua-filter sidenote.lua (HTML live-preview only)
    - --to (caller decides output format)
    """
    md_text = doc_path.read_text(encoding="utf-8")
    has_own_csl = re.search(r"^csl:", md_text, re.MULTILINE) is not None
    number_sections = re.search(r"^number-sections:\s*true", md_text, re.MULTILINE) is not None

    # Load external LaTeX macros file if specified in frontmatter
    macros_match = re.search(r"^macros:\s*['\"]?(.+?)['\"]?\s*$", md_text, re.MULTILINE)
    if macros_match:
        macros_path = doc_path.parent / macros_match.group(1).strip()
        if macros_path.is_file():
            macros_content = macros_path.read_text(encoding="utf-8")
            fm_end = re.search(
                r"\A---\s*\n.*?^(---|\.\.\.)\s*$", md_text, re.MULTILINE | re.DOTALL
            )
            if fm_end:
                pos = fm_end.end()
                md_text = md_text[:pos] + "\n" + macros_content + "\n" + md_text[pos:]

    cmd = ["pandoc"]
    if _HAS_CROSSREF:
        cmd.extend([
            "--filter", "pandoc-crossref",
            "--metadata=linkReferences:true",
            "--metadata=secPrefix:§",
        ])
    cmd += [
        "--citeproc",
        "--metadata=link-citations:true",
        "--from=markdown+tex_math_single_backslash",
    ]
    if not has_own_csl:
        cmd.extend(["--csl", _DEFAULT_CSL])
    if number_sections:
        cmd.append("--number-sections")

    return cmd, md_text
```

Refactored `_render_pandoc_sync` (replaces existing function):

```python
def _render_pandoc_sync(doc_path: Path, sidenotes: bool = False) -> str:
    """Render markdown to HTML fragment using Pandoc (blocking)."""
    cmd, md_text = _build_pandoc_base_cmd(doc_path)
    cmd += [
        "--katex",
        "--section-divs",
        "--syntax-highlighting=pygments",
        "--to=html5",
        "--template=" + _FRAGMENT_TEMPLATE,
    ]
    if sidenotes:
        cmd.extend(["--lua-filter", _SIDENOTE_FILTER])

    result = subprocess.run(
        cmd,
        input=md_text,
        capture_output=True,
        text=True,
        check=True,
        cwd=str(doc_path.parent),
    )
    return result.stdout
```

- [ ] **Step 4: Run regression tests**

Run: `uv run pytest tests/test_server.py -v`
Expected: All PASS — existing behavior preserved

- [ ] **Step 5: Write test for `_build_pandoc_base_cmd` directly**

Add to `tests/test_server.py`:

```python
from scholia.server import _build_pandoc_base_cmd


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
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_server.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add scholia/server.py tests/test_server.py
git commit -m "Refactor: extract _build_pandoc_base_cmd() for shared Pandoc args"
```

---

### Task 2: Add `_render_export_sync()` and `/api/export-pdf` endpoint

**Files:**
- Modify: `scholia/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write test for the export endpoint**

Add to `tests/test_server.py`:

```python
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
```

- [ ] **Step 2: Run tests to see them fail**

Run: `uv run pytest tests/test_server.py::test_export_pdf_endpoint_html_fallback tests/test_server.py::test_export_pdf_endpoint_missing_file -v`
Expected: FAIL (route doesn't exist yet)

- [ ] **Step 3: Write test for `_render_export_sync` with HTML and LaTeX formats**

These formats don't need a LaTeX engine, so they always work.

```python
from scholia.server import _render_export_sync


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
```

- [ ] **Step 4: Run tests to see them fail**

Run: `uv run pytest tests/test_server.py::test_render_export_html tests/test_server.py::test_render_export_latex tests/test_server.py::test_render_export_returns_bytes -v`
Expected: FAIL (`_render_export_sync` doesn't exist)

- [ ] **Step 5: Implement `_render_export_sync`, `render_export`, and the endpoint**

Add to `scholia/server.py` after `render_pandoc()`:

```python
def _render_export_sync(
    doc_path: Path, fmt: str, output_path: Path | None = None,
    pdf_engine: str | None = None,
) -> bytes | None:
    """Export document to pdf/html/latex. Returns bytes if output_path is None."""
    cmd, md_text = _build_pandoc_base_cmd(doc_path)
    cmd.append("--standalone")
    cmd.append("--resource-path=" + str(doc_path.parent))

    if fmt == "pdf":
        cmd.append("--to=pdf")
        if pdf_engine:
            cmd.append("--pdf-engine=" + pdf_engine)
    elif fmt == "html":
        cmd += [
            "--to=html5",
            "--katex",
            "--section-divs",
            "--syntax-highlighting=pygments",
        ]
    elif fmt == "latex":
        cmd.append("--to=latex")
    else:
        raise ValueError(f"Unsupported export format: {fmt}")

    if output_path:
        cmd.extend(["-o", str(output_path)])
        subprocess.run(
            cmd, input=md_text, capture_output=True, text=True, check=True,
            cwd=str(doc_path.parent),
        )
        return None
    else:
        # Return bytes for server streaming. We encode md_text to bytes and
        # omit text=True so stdout is captured as raw bytes (needed for PDF
        # binary output). Pandoc writes to stdout when no -o is given.
        result = subprocess.run(
            cmd, input=md_text.encode(), capture_output=True, check=True,
            cwd=str(doc_path.parent),
        )
        return result.stdout


async def render_export(
    doc_path: Path, fmt: str, output_path: Path | None = None,
    pdf_engine: str | None = None,
) -> bytes | None:
    """Export document without blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _render_export_sync, doc_path, fmt, output_path, pdf_engine
    )
```

Add the route in `_setup_routes()`:

```python
self.app.router.add_get("/api/export-pdf", self._handle_export_pdf)
```

Add the handler in `ScholiaServer`:

```python
async def _handle_export_pdf(self, request):
    """Export document to PDF and return the file."""
    file_param = request.query.get("file")
    if not file_param:
        return web.json_response({"error": "Missing file parameter"}, status=400)

    file_path = Path(file_param)
    if not file_path.is_absolute():
        file_path = self.launch_dir / file_path
    doc_path = file_path.resolve()

    if not doc_path.exists():
        return web.json_response({"error": f"File not found: {doc_path}"}, status=404)

    try:
        pdf_bytes = await render_export(doc_path, "pdf")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        if "pdf" in stderr.lower() or "latex" in stderr.lower() or "xelatex" in stderr.lower() or "tectonic" in stderr.lower():
            return web.json_response({
                "error": "PDF export requires a LaTeX engine (xelatex, tectonic, etc.).",
                "fallback": "print",
            }, status=422)
        return web.json_response({"error": f"Export failed: {stderr}"}, status=500)

    return web.Response(
        body=pdf_bytes,
        content_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{doc_path.stem}.pdf"',
        },
    )
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/test_server.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add scholia/server.py tests/test_server.py
git commit -m "Add multi-format Pandoc export and /api/export-pdf endpoint"
```

---

### Task 3: Add `scholia export` CLI subcommand

**Files:**
- Modify: `scholia/cli.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write tests for the CLI export command**

Add to `tests/test_core.py`:

```python
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


def test_cli_export_default_output_name(tmp_doc, monkeypatch):
    """Without -o, export writes <stem>.pdf (or .html/.tex) in cwd."""
    monkeypatch.chdir(tmp_doc.parent)
    code, stdout, _ = _run_cli("export", str(tmp_doc), "--to", "html")
    assert code == 0
    expected = tmp_doc.parent / "test.html"
    assert expected.exists()


def test_cli_export_missing_file():
    """Export of nonexistent file returns error."""
    code, _, stderr = _run_cli("export", "/nonexistent/doc.md", "--to", "html")
    assert code == 1


def test_cli_export_pdf_no_latex(tmp_doc, tmp_path, monkeypatch):
    """PDF export without LaTeX engine shows clear error message."""
    import shutil
    # Only test if no LaTeX engine is available
    if shutil.which("xelatex") or shutil.which("tectonic") or shutil.which("lualatex") or shutil.which("pdflatex"):
        pytest.skip("LaTeX engine available; can't test missing-engine error")
    out = tmp_path / "out.pdf"
    code, _, stderr = _run_cli("export", str(tmp_doc), "--to", "pdf", "-o", str(out))
    assert code == 1
    assert "latex" in stderr.lower() or "pdf" in stderr.lower()
```

- [ ] **Step 2: Run tests to see them fail**

Run: `uv run pytest tests/test_core.py::test_cli_export_html tests/test_core.py::test_cli_export_latex -v`
Expected: FAIL (subcommand doesn't exist)

- [ ] **Step 3: Implement `cmd_export` and add subparser**

Add to `scholia/cli.py`, in the commands section (after `cmd_unresolve`):

```python
def cmd_export(args):
    from scholia.server import _render_export_sync
    import subprocess

    doc = Path(args.doc)
    if not doc.exists():
        print(f"Error: file not found: {args.doc}", file=sys.stderr)
        sys.exit(1)

    doc = doc.resolve()
    fmt = args.to

    if args.output:
        output = Path(args.output)
    else:
        ext_map = {"pdf": ".pdf", "html": ".html", "latex": ".tex"}
        output = Path.cwd() / (doc.stem + ext_map[fmt])

    try:
        _render_export_sync(doc, fmt, output, pdf_engine=args.pdf_engine)
    except subprocess.CalledProcessError as e:
        stderr_text = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or str(e))
        if fmt == "pdf" and ("latex" in stderr_text.lower() or "pdf" in stderr_text.lower()):
            print(
                "Error: PDF export requires a LaTeX engine (xelatex, tectonic, etc.).\n"
                "Install one, or use --to html or --to latex instead.",
                file=sys.stderr,
            )
        else:
            print(f"Error: export failed: {stderr_text}", file=sys.stderr)
        sys.exit(1)

    print(output)
```

Add the subparser in `main()`, after the `unresolve` subparser:

```python
    # export
    p_export = sub.add_parser(
        "export",
        help="Export document to PDF, standalone HTML, or LaTeX",
    )
    p_export.add_argument("doc", help="Markdown document path")
    p_export.add_argument(
        "--to", "-t", default="pdf", choices=["pdf", "html", "latex"],
        help="Output format (default: pdf)",
    )
    p_export.add_argument(
        "--output", "-o", default=None, metavar="PATH",
        help="Output file path (default: <input-stem>.<ext> in cwd)",
    )
    p_export.add_argument(
        "--pdf-engine", default=None, metavar="ENGINE",
        help="LaTeX engine for PDF output (e.g. xelatex, tectonic)",
    )
```

Add `"export": cmd_export` to the `handlers` dict.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_core.py -k export -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add scholia/cli.py tests/test_core.py
git commit -m "Add 'scholia export' CLI subcommand for PDF, HTML, LaTeX output"
```

---

### Task 4: Add Export PDF button in browser Options menu

**Files:**
- Modify: `scholia/static/scholia.js:449-591` (Options menu in `renderToolbar`)

- [ ] **Step 1: Add Export PDF row to the Options menu**

In `scholia/static/scholia.js`, inside `renderToolbar()`'s Options menu builder, after the Zoom row table append (`tbl.appendChild(zoomRow);` at ~line 587) and before `menu.appendChild(tbl);` (~line 589), add:

```javascript
      // Export PDF row (separator + button, visually distinct from toggles)
      var exportRow = document.createElement('tr');
      exportRow.className = 'scholia-export-row';
      var exportTd = document.createElement('td');
      exportTd.setAttribute('colspan', '2');
      var exportBtn = document.createElement('button');
      exportBtn.className = 'scholia-export-btn';
      exportBtn.textContent = 'Export PDF';
      exportBtn.addEventListener('click', function () {
        exportBtn.textContent = 'Exporting\u2026';
        exportBtn.disabled = true;
        var fileParam = encodeURIComponent(window.__SCHOLIA_DOC_FULLPATH__ || '');
        fetch('/api/export-pdf?file=' + fileParam)
          .then(function (resp) {
            if (resp.ok) {
              return resp.blob().then(function (blob) {
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url;
                var name = (window.__SCHOLIA_DOC_PATH__ || 'document').split('/').pop();
                a.download = name.replace(/\.[^.]+$/, '') + '.pdf';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                menu.remove();
              });
            } else {
              return resp.json().then(function (data) {
                menu.remove();
                if (data.fallback === 'print') {
                  showExportWarning('PDF export requires a LaTeX engine. Using browser print instead.');
                  setTimeout(function () { window.print(); }, 300);
                } else {
                  showExportWarning('Export failed: ' + (data.error || 'unknown error'));
                }
              });
            }
          })
          .catch(function (err) {
            menu.remove();
            showExportWarning('Export failed: ' + err.message);
          });
      });
      exportTd.appendChild(exportBtn);
      exportRow.appendChild(exportTd);
      tbl.appendChild(exportRow);
```

- [ ] **Step 2: Add `showExportWarning` helper**

Add near the `wsSend` function area (around line 326):

```javascript
  function showExportWarning(text) {
    var banner = document.createElement('div');
    banner.className = 'scholia-export-warning';
    banner.textContent = text;
    banner.style.cursor = 'pointer';
    banner.addEventListener('click', function () { banner.remove(); });
    document.body.appendChild(banner);
    setTimeout(function () { banner.remove(); }, 8000);
  }
```

- [ ] **Step 3: Add CSS for export button and warning**

Add to `scholia/static/scholia.css`:

```css
/* Export PDF in Options menu */
.scholia-export-row td {
  padding-top: 6px;
  border-top: 1px solid var(--s-border);
}
.scholia-export-btn {
  width: 100%;
  padding: 4px 8px;
  cursor: pointer;
  border: 1px solid var(--s-border);
  border-radius: var(--s-radius);
  background: var(--s-surface);
  color: var(--s-text);
}
.scholia-export-btn:hover {
  background: var(--s-card-hover);
}

/* Export warning banner */
.scholia-export-warning {
  position: fixed;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  background: #d97706;
  color: white;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  z-index: 10000;
  pointer-events: auto;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}
```

- [ ] **Step 4: Manual test**

Run: `uv run scholia view examples/example-notes.md` (or any markdown file)
In the browser: click Options → Export PDF. Verify either a PDF downloads or a warning appears with browser print.

- [ ] **Step 5: Run existing test suite to check for regressions**

Run: `uv run pytest -v`
Expected: All PASS (especially `test_form_elements_have_name_or_id`)

- [ ] **Step 6: Commit**

```bash
git add scholia/static/scholia.js scholia/static/scholia.css
git commit -m "Add Export PDF button to browser Options menu"
```

---

### Task 5: WebSocket exponential backoff

**Files:**
- Modify: `scholia/static/scholia.js:274-323` (the `connectWS` function)

- [ ] **Step 1: Implement exponential backoff**

Replace the existing `connectWS` function and its `onclose` handler in `scholia/static/scholia.js`:

Change the top-level variables (near line 9):

```javascript
  var ws;
  var wsAttempt = 0;
```

Replace the `connectWS` function (~lines 274-324):

```javascript
  function connectWS() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(proto + '//' + location.host + '/ws');

    ws.onopen = function () {
      wsAttempt = 0;
      hideDisconnectBanner();
      wsSend({type: 'watch', file: window.__SCHOLIA_DOC_FULLPATH__});
    };

    ws.onmessage = function (e) {
      var msg = JSON.parse(e.data);
      if (msg.type === 'doc_update') {
        if (msg.sidenotes !== undefined) {
          sidenotesEnabled = msg.sidenotes;
          docEl.classList.toggle('scholia-no-sidenotes', !sidenotesEnabled);
          renderToolbar();
        }
        docEl.innerHTML = msg.html;
        buildToc();
        rerenderMath();
        decorateCodeBlocks();
        setupCitationTooltips();
        if (!sidebarHidden) { reanchorAll(); positionCards(); }
      } else if (msg.type === 'comments_update') {
        comments = msg.comments;
        scheduleRender();
        // Refresh overlay if open
        if (activeOverlay) {
          var overlayAnnId = activeOverlay.annotationId;
          for (var ci = 0; ci < comments.length; ci++) {
            if (comments[ci].id === overlayAnnId) {
              closeOverlay();
              openOverlay(comments[ci]);
              break;
            }
          }
        }
      } else if (msg.type === 'rendered_markdown') {
        var cb = pandocCallbacks.get(msg.request_id);
        if (cb) {
          cb(msg.html);
          pandocCallbacks.delete(msg.request_id);
        }
      } else if (msg.type === 'error') {
        console.warn('Scholia server error:', msg.message);
      }
    };

    ws.onerror = function (e) {
      console.warn('Scholia WebSocket error:', e);
    };

    ws.onclose = function () {
      showDisconnectBanner();
      var delay = Math.min(2000 * Math.pow(2, wsAttempt), 30000);
      wsAttempt++;
      setTimeout(connectWS, delay);
    };
  }
```

- [ ] **Step 2: Verify no regressions**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add scholia/static/scholia.js
git commit -m "Add exponential backoff to WebSocket reconnection"
```

---

### Task 6: Disconnect banner (UI + CSS)

**Files:**
- Modify: `scholia/static/scholia.js`
- Modify: `scholia/static/scholia.css`

- [ ] **Step 1: Add banner DOM element and show/hide functions**

In `scholia/static/scholia.js`, add near the top of the IIFE (after the variable declarations, around line 31):

```javascript
  // Disconnect banner
  var disconnectBanner = document.createElement('div');
  disconnectBanner.className = 'scholia-disconnect-banner';
  disconnectBanner.textContent = 'Reconnecting\u2026';
  document.body.appendChild(disconnectBanner);
  var disconnectShowTimer = null;

  function showDisconnectBanner() {
    if (disconnectShowTimer) return;  // already pending
    disconnectShowTimer = setTimeout(function () {
      disconnectBanner.classList.add('visible');
      disconnectShowTimer = null;
    }, 500);
  }

  function hideDisconnectBanner() {
    if (disconnectShowTimer) {
      clearTimeout(disconnectShowTimer);
      disconnectShowTimer = null;
    }
    disconnectBanner.classList.remove('visible');
  }
```

- [ ] **Step 2: Add CSS styles for the disconnect banner**

Add to `scholia/static/scholia.css`:

The toolbar uses `position: sticky` with `padding: 0.3rem 0.75rem` and `font-size: 0.72rem`, giving an effective height of ~28-32px. Position the banner just below it with a safe fallback.

```css
/* Disconnect banner */
.scholia-disconnect-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(217, 119, 6, 0.9);
  color: white;
  font-size: 12px;
  font-family: var(--s-sans);
  z-index: 99;  /* below toolbar (z-index: 100) so it slides out from under it */
  pointer-events: none;
  opacity: 0;
  transform: translateY(-100%);
  transition: opacity 0.3s, transform 0.3s;
}
.scholia-disconnect-banner.visible {
  opacity: 1;
  transform: translateY(0);
}
body.scholia-dark .scholia-disconnect-banner {
  background: rgba(180, 83, 9, 0.9);
}
```

Note: z-index 99 puts the banner below the sticky toolbar (z-index 100). The banner slides down from behind the toolbar when visible — a clean visual effect.

- [ ] **Step 3: Manual test**

Run: `uv run scholia view examples/example-notes.md`
In the browser: kill the server (Ctrl+C), observe the banner slides in after ~500ms with "Reconnecting...". Restart the server: banner disappears immediately.

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add scholia/static/scholia.js scholia/static/scholia.css
git commit -m "Add disconnect banner with delayed show/immediate hide"
```

---

### Task 7: Final integration test and cleanup

**Files:**
- Test: `tests/test_server.py`

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 2: Manual smoke test of both features together**

Run: `uv run scholia view examples/example-notes.md`

Verify:
1. Options menu has "Export PDF" at the bottom
2. Clicking "Export PDF" either downloads a PDF or shows warning + browser print
3. Kill server → banner appears after ~500ms → restart → banner disappears
4. All existing functionality (comments, TOC, theme, zoom) still works

- [ ] **Step 3: Test CLI export**

```bash
uv run scholia export examples/example-notes.md --to html -o /tmp/test-export.html
uv run scholia export examples/example-notes.md --to latex -o /tmp/test-export.tex
# If LaTeX available:
uv run scholia export examples/example-notes.md --to pdf -o /tmp/test-export.pdf
```

**Note on JS backoff test:** The spec calls for a unit test of the backoff calculation, but the project has no JS test infrastructure. The formula (`min(2000 * 2^n, 30000)`) is simple enough to verify by inspection and manual testing. A JS unit test can be added when frontend testing is set up (tracked in `project_frontend_refactoring.md`).

- [ ] **Step 4: Commit any final adjustments**

```bash
git add -A
git commit -m "Integration test and polish for PDF export + WS resilience"
```
