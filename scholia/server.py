"""Asyncio server: Pandoc render, file watch, WebSocket push."""

import asyncio
import json
import os
import re
import signal
import shutil
import subprocess
import sys
from pathlib import Path

from aiohttp import web
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from scholia.comments import (
    annotation_path,
    append_comment,
    append_reply,
    edit_body,
    get_human_username,
    load_comments,
    reanchor,
    resolve,
    unresolve,
)
from scholia.state import load_state, mark_read, mark_unread


def _check_pandoc():
    """Verify Pandoc is installed."""
    if shutil.which("pandoc") is None:
        raise RuntimeError("Pandoc not found. Install it from https://pandoc.org/installing.html")


_MERMAID_FILTER = str(Path(__file__).parent / "filters" / "mermaid.lua")
_SIDENOTE_FILTER = str(Path(__file__).parent / "filters" / "sidenote.lua")
_DEFAULT_CSL = str(Path(__file__).parent / "static" / "apa.csl")
_FRAGMENT_TEMPLATE = str(Path(__file__).parent / "pandoc-fragment.html")
_HAS_CROSSREF = shutil.which("pandoc-crossref") is not None
_MARKDOWN_EXTENSIONS = {".md", ".markdown", ".qmd", ".rmd"}


def _is_markdown(path: Path) -> bool:
    return path.suffix.lower() in _MARKDOWN_EXTENSIONS


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI color/style escape sequences."""
    return _ANSI_RE.sub("", text)


def _has_footnotes(md_text: str) -> bool:
    """Check if markdown contains footnote syntax ([^...] or ^[...])."""
    return bool(re.search(r"\[\^|\^\[", md_text))


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
        cmd.extend(
            [
                "--filter",
                "pandoc-crossref",
                "--metadata=linkReferences:true",
                "--metadata=secPrefix:§",
            ]
        )
    cmd += [
        "--lua-filter",
        _MERMAID_FILTER,
        "--citeproc",
        "--metadata=link-citations:true",
        "--from=markdown+tex_math_single_backslash",
    ]
    if not has_own_csl:
        cmd.extend(["--csl", _DEFAULT_CSL])
    if number_sections:
        cmd.append("--number-sections")

    return cmd, md_text


def _render_pandoc_sync(doc_path: Path, sidenotes: bool = False) -> tuple[str, str]:
    """Render markdown to HTML fragment using Pandoc (blocking).

    Returns (html, stderr) — stderr may contain warnings even on success.
    """
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
        cwd=str(doc_path.parent),
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result.stdout, result.stderr


def _find_quarto_python(doc_path: Path) -> str | None:
    """Find Python for Quarto code execution.

    Priority: QUARTO_PYTHON env > .venv near document > active VIRTUAL_ENV.
    Document-local venv wins over the active venv because the server's
    own venv (e.g., set by ``uv run``) typically lacks Jupyter/numpy.
    Returns None if nothing found (Quarto uses its own default).
    """
    explicit = os.environ.get("QUARTO_PYTHON")
    if explicit:
        return explicit
    # Walk up from document directory looking for .venv
    d = doc_path.parent.resolve()
    for _ in range(10):
        candidate = d / ".venv" / "bin" / "python"
        if candidate.is_file():
            return str(candidate)
        parent = d.parent
        if parent == d:
            break
        d = parent
    # Fall back to active venv
    active_venv = os.environ.get("VIRTUAL_ENV")
    if active_venv:
        candidate = Path(active_venv) / "bin" / "python"
        if candidate.is_file():
            return str(candidate)
    return None


_QUARTO_EXTENSIONS = {".qmd", ".rmd"}


def _is_quarto(path: Path) -> bool:
    return path.suffix.lower() in _QUARTO_EXTENSIONS


def _render_quarto_sync(doc_path: Path, use_defaults: bool = True) -> tuple[str, str]:
    """Render a Quarto document and return the full HTML page (blocking).

    Runs ``quarto render`` in the document's own directory so that
    ``<stem>_files/`` persists for the /quarto-assets/ route to serve.
    Asset paths are rewritten from ``<stem>_files/`` to ``/quarto-assets/``.

    Returns (html, stderr) — stderr may contain warnings even on success.
    The caller injects scholia's overlay (sidebar, scripts) into this page.
    """
    quarto = shutil.which("quarto")
    if not quarto:
        raise RuntimeError(
            "Quarto is not installed. Install from https://quarto.org/docs/get-started/"
        )

    out_file = doc_path.with_suffix(".html")
    cmd = [
        quarto,
        "render",
        str(doc_path.resolve()),
        "--to",
        "html",
        "-M",
        "html-math-method:katex",
    ]
    if use_defaults:
        cmd += [
            "--metadata-file",
            str(Path(__file__).parent / "data" / "quarto-defaults.yml"),
        ]
    env = {**os.environ}
    py = _find_quarto_python(doc_path)
    if py:
        env["QUARTO_PYTHON"] = py
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(doc_path.parent),
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"quarto render failed: {result.stderr}")

    html = out_file.read_text(encoding="utf-8")
    stem = doc_path.stem

    # Rewrite local asset paths to go through /quarto-assets/
    html = html.replace(f"{stem}_files/", "/quarto-assets/")

    return html, result.stderr


async def render_doc(
    doc_path: Path, sidenotes: bool = False, quarto_use_defaults: bool = True
) -> tuple[str, str]:
    """Render a document to HTML, choosing the right pipeline.

    Returns (html, stderr).
    For Quarto documents html is a complete HTML page.
    For Pandoc documents html is an HTML fragment.
    """
    loop = asyncio.get_running_loop()
    if _is_quarto(doc_path):
        return await loop.run_in_executor(None, _render_quarto_sync, doc_path, quarto_use_defaults)
    return await loop.run_in_executor(None, _render_pandoc_sync, doc_path, sidenotes)


async def render_pandoc(doc_path: Path, sidenotes: bool = False) -> tuple[str, str]:
    """Render markdown to HTML fragment without blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _render_pandoc_sync, doc_path, sidenotes)


def _render_export_sync(
    doc_path: Path,
    fmt: str,
    output_path: Path | None = None,
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
        result = subprocess.run(
            cmd,
            input=md_text,
            capture_output=True,
            text=True,
            check=True,
            cwd=str(doc_path.parent),
        )
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        return None
    else:
        # Return bytes for server streaming. We encode md_text to bytes and
        # omit text=True so stdout is captured as raw bytes (needed for PDF
        # binary output). Pandoc writes to stdout when no -o is given.
        result = subprocess.run(
            cmd,
            input=md_text.encode(),
            capture_output=True,
            check=True,
            cwd=str(doc_path.parent),
        )
        if result.stderr:
            sys.stderr.buffer.write(result.stderr)
        return result.stdout


def _render_quarto_export_sync(doc_path: Path, fmt: str) -> bytes:
    """Export a Quarto document to pdf/html/etc. Returns bytes."""
    import tempfile

    quarto = shutil.which("quarto")
    if not quarto:
        raise RuntimeError(
            "Quarto is not installed. Install from https://quarto.org/docs/get-started/"
        )

    with tempfile.TemporaryDirectory() as tmp:
        out_name = f"output.{fmt}"
        cmd = [
            quarto,
            "render",
            str(doc_path.resolve()),
            "--to",
            fmt,
            "--output",
            out_name,
            "--output-dir",
            tmp,
        ]
        env = {**os.environ}
        py = _find_quarto_python(doc_path)
        if py:
            env["QUARTO_PYTHON"] = py
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(doc_path.parent),
            timeout=120,
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, output=result.stdout, stderr=result.stderr
            )
        return Path(tmp, out_name).read_bytes()


async def render_export(
    doc_path: Path,
    fmt: str,
    output_path: Path | None = None,
    pdf_engine: str | None = None,
) -> bytes | None:
    """Export document without blocking the event loop."""
    loop = asyncio.get_running_loop()
    if _is_quarto(doc_path):
        return await loop.run_in_executor(None, _render_quarto_export_sync, doc_path, fmt)
    return await loop.run_in_executor(
        None, _render_export_sync, doc_path, fmt, output_path, pdf_engine
    )


def _extract_bibliography(doc_path: Path) -> tuple[str | None, str | None]:
    """Extract bibliography and csl paths from document YAML frontmatter."""
    try:
        md_text = doc_path.read_text(encoding="utf-8")
    except OSError:
        return None, None
    m = re.match(r"^---\n(.*?)\n---", md_text, re.DOTALL)
    if not m:
        return None, None
    bib = None
    csl = None
    for line in m.group(1).splitlines():
        bm = re.match(r"^bibliography:\s*(.+?)\s*$", line)
        if bm:
            bib = bm.group(1).strip("\"'")
        cm = re.match(r"^csl:\s*(.+?)\s*$", line)
        if cm:
            csl = cm.group(1).strip("\"'")
    return bib, csl


def _render_markdown_fragment_sync(
    text: str,
    cwd: str = ".",
    bibliography: str | None = None,
    csl: str | None = None,
) -> str:
    """Render a markdown fragment to HTML via Pandoc (blocking)."""
    cmd = [
        "pandoc",
        "--katex",
        "--citeproc",
        "--metadata=link-citations:true",
        "--from=markdown+tex_math_single_backslash",
        "--to=html5",
    ]
    if bibliography:
        cmd.append("--bibliography=" + bibliography)
    if csl:
        cmd.append("--csl=" + csl)
    elif not csl:
        cmd.append("--csl=" + _DEFAULT_CSL)
    result = subprocess.run(
        cmd,
        input=text,
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    return result.stdout


async def render_markdown_fragment(
    text: str,
    cwd: str = ".",
    bibliography: str | None = None,
    csl: str | None = None,
) -> str:
    """Render a markdown fragment without blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _render_markdown_fragment_sync, text, cwd, bibliography, csl
    )


def _extract_title(markdown_text: str) -> str:
    """Extract title from YAML frontmatter, or return 'Scholia'."""
    m = re.match(r"^---\n(.*?)\n---", markdown_text, re.DOTALL)
    if not m:
        return "Scholia"
    for line in m.group(1).splitlines():
        tm = re.match(r"""^title:\s*["']?(.+?)["']?\s*$""", line)
        if tm:
            return tm.group(1)
    return "Scholia"


def _inject_scholia_into_quarto(
    quarto_html: str,
    doc_path: Path,
    display_path: str = "",
    include_theme_css: bool = True,
) -> str:
    """Inject scholia's sidebar overlay into a complete Quarto HTML page.

    Instead of extracting Quarto content into scholia's template, we take
    Quarto's full rendered page and inject scholia on top of it — the same
    approach as Hypothesis.  Quarto's CSS, JS, and page structure are
    completely preserved.
    """
    dp = (display_path or str(doc_path)).replace("\\", "/")

    # Add id="scholia-doc" to <main> so scholia.js can find the content element
    quarto_html = re.sub(
        r"<main\b([^>]*)>",
        r'<main id="scholia-doc"\1>',
        quarto_html,
        count=1,
    )

    # Inject highlight CSS + comment rendering libs before </head>
    # fmt: off
    head_inject = (                                                     # noqa: E501
        "  <style>\n"
        "    mark.scholia-highlight {"
        " background:rgba(255,220,100,.35); border-radius:2px; cursor:pointer }\n"
        "    mark.scholia-highlight.scholia-highlight-active,"
        " mark.scholia-highlight:hover {"
        " background:rgba(255,200,50,.55) }\n"
        "    mark.scholia-highlight.scholia-highlight-resolved {"
        " background:rgba(200,200,200,.25) }\n"
        "    mark.scholia-highlight.scholia-highlight-resolved"
        ".scholia-highlight-active,\n"
        "    mark.scholia-highlight.scholia-highlight-resolved:hover {"
        " background:rgba(180,180,180,.35) }\n"
        "    mark.scholia-highlight.scholia-pulse {"
        " animation:scholia-pulse .6s ease-out }\n"
        "    @keyframes scholia-pulse {\n"
        "      0%{box-shadow:0 0 0 0 rgba(255,200,50,.7)}\n"
        "      100%{box-shadow:0 0 0 8px rgba(255,200,50,0)} }\n"
        "  </style>\n"
        + (
            '  <link id="scholia-quarto-theme" rel="stylesheet"'
            ' href="/static/quarto-theme.css">\n'
            if include_theme_css
            else ""
        )
        + '  <script defer src="https://cdn.jsdelivr.net/npm/'
        'markdown-it@14.1.0/dist/markdown-it.min.js"></script>\n'
        '  <script defer src="https://cdn.jsdelivr.net/npm/'
        'markdown-it-texmath@1.0.0/texmath.min.js"></script>\n'
        '  <script defer src="https://cdn.jsdelivr.net/npm/'
        'mermaid@11/dist/mermaid.min.js"></script>\n'
    )
    # fmt: on
    quarto_html = quarto_html.replace("</head>", head_inject + "</head>")

    # Inject <scholia-sidebar> + config + scripts before </body>
    comments = load_comments(doc_path)
    state = load_state(doc_path)
    body_inject = f"""
  <scholia-sidebar></scholia-sidebar>
  <script>
  window.__SCHOLIA_CREATOR__ = {json.dumps(get_human_username())};
  window.__SCHOLIA_DOC_PATH__ = {json.dumps(dp)};
  window.__SCHOLIA_DOC_FULLPATH__ = {json.dumps(str(doc_path).replace(chr(92), "/"))};
  window.__SCHOLIA_SIDENOTES__ = false;
  window.__SCHOLIA_COMMENTS__ = {json.dumps(comments)};
  window.__SCHOLIA_STATE__ = {json.dumps(state)};
  window.__SCHOLIA_READONLY__ = false;
  window.__SCHOLIA_IS_QUARTO__ = true;
  </script>
  <script src="/static/vendor/dom-anchor-text-quote.js"></script>
  <script src="/static/scholia.js"></script>
"""
    quarto_html = quarto_html.replace("</body>", body_inject + "</body>")

    return quarto_html


async def build_page(
    doc_path: Path,
    template: str,
    sidenotes: bool = False,
    display_path: str = "",
    quarto_theme: str = "scholia",
) -> str:
    """Build full HTML page from template + rendered markdown + comments."""
    use_defaults = quarto_theme != "default"
    html, _stderr = await render_doc(
        doc_path, sidenotes=sidenotes, quarto_use_defaults=use_defaults
    )

    if _is_quarto(doc_path):
        return _inject_scholia_into_quarto(
            html,
            doc_path,
            display_path=display_path,
            include_theme_css=use_defaults,
        )

    title = _extract_title(doc_path.read_text(encoding="utf-8"))
    return _fill_template(
        template,
        title=title,
        html=html,
        doc_path=doc_path,
        display_path=display_path,
        sidenotes=sidenotes,
        comments=load_comments(doc_path),
        state=load_state(doc_path),
    )


def _is_binary(path: Path) -> bool:
    """Heuristic: file is binary if the first 8KB contains null bytes."""
    try:
        chunk = path.read_bytes()[:8192]
        return b"\x00" in chunk
    except OSError:
        return False


def _fill_template(
    template: str,
    *,
    title: str,
    html: str,
    doc_path: Path,
    display_path: str = "",
    sidenotes: bool = False,
    comments: list | None = None,
    state: dict | None = None,
    readonly: bool = False,
) -> str:
    """Fill the Pandoc page template with the given content and metadata."""
    page = template.replace("{{TITLE}}", title)
    page = page.replace("{{PANDOC_HTML}}", html)
    page = page.replace("{{CREATOR_NAME}}", json.dumps(get_human_username()))
    dp = (display_path or str(doc_path)).replace("\\", "/")
    page = page.replace("{{DOC_PATH}}", json.dumps(dp))
    page = page.replace("{{DOC_FULLPATH}}", json.dumps(str(doc_path).replace("\\", "/")))
    page = page.replace("{{SIDENOTES_ENABLED}}", json.dumps(sidenotes))
    page = page.replace("{{COMMENTS_JSON}}", json.dumps(comments or []))
    page = page.replace("{{STATE_JSON}}", json.dumps(state or {}))
    page = page.replace("{{READONLY}}", json.dumps(readonly))
    page = page.replace("{{QUARTO_HEAD}}", "")
    page = page.replace("{{IS_QUARTO}}", json.dumps(False))
    content_css = '<link rel="stylesheet" href="/static/scholia.css">'
    page = page.replace("{{CONTENT_CSS}}", content_css)
    return page


def _build_raw_page(
    doc_path: Path,
    template: str,
    display_path: str = "",
    force: bool = False,
) -> str:
    """Build HTML page for a non-markdown file, displayed as raw text."""
    import html as html_mod

    if not force and _is_binary(doc_path):
        content = (
            "<p>This appears to be a binary file.</p>"
            f'<p><a href="/?file={html_mod.escape(display_path or str(doc_path))}&amp;raw=1">'
            "Display anyway</a></p>"
        )
        return _fill_template(
            template,
            title=doc_path.name + " — Scholia",
            html=content,
            doc_path=doc_path,
            display_path=display_path,
            readonly=True,
        )
    raw = doc_path.read_text(encoding="utf-8", errors="replace")
    escaped = html_mod.escape(raw)
    content = f'<pre class="scholia-raw-file"><code>{escaped}</code></pre>'
    return _fill_template(
        template,
        title=doc_path.name + " — Scholia",
        html=content,
        doc_path=doc_path,
        display_path=display_path,
        comments=load_comments(doc_path),
        state=load_state(doc_path),
    )


class _FileChangeHandler(FileSystemEventHandler):
    """Watch for changes to any registered doc or its .scholia.jsonl."""

    def __init__(self, server: "ScholiaServer", loop: asyncio.AbstractEventLoop):
        self.server = server
        self.loop = loop

    def _check_path(self, path: Path):
        resolved = path.resolve()
        for doc_path in list(self.server.ws_clients.keys()):
            if resolved == doc_path:
                self.loop.call_soon_threadsafe(self.server._on_file_change, doc_path, "doc")
            elif resolved == annotation_path(doc_path).resolve():
                self.loop.call_soon_threadsafe(self.server._on_file_change, doc_path, "comments")

    def on_modified(self, event):
        self._check_path(Path(event.src_path))

    def on_created(self, event):
        self._check_path(Path(event.src_path))

    def on_moved(self, event):
        self._check_path(Path(event.dest_path))


class ScholiaServer:
    def __init__(
        self,
        doc_path: str,
        host: str = "127.0.0.1",
        port: int = 8088,
        ephemeral: bool = False,
        open_browser: bool = True,
    ):
        _check_pandoc()
        self.display_path = doc_path  # as given on command line
        self.doc_path = Path(doc_path).resolve()
        if not self.doc_path.exists():
            raise FileNotFoundError(f"Document not found: {self.doc_path}")
        self.host = host
        self.port = port
        self.launch_dir = Path.cwd().resolve()
        self.ws_clients: dict[Path, set[web.WebSocketResponse]] = {}
        self.ws_file: dict[web.WebSocketResponse, Path] = {}
        self.ws_sidenotes: dict[web.WebSocketResponse, bool] = {}
        self.template = self._load_template()
        self.app = web.Application()
        self._setup_routes()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._debounce_handles: dict[tuple, asyncio.TimerHandle] = {}
        self._observers: dict[Path, Observer] = {}  # parent_dir -> Observer
        self._observer_refcount: dict[Path, int] = {}  # parent_dir -> count
        self._ephemeral = ephemeral
        self._open_browser = open_browser
        self.render_errors: dict[Path, str] = {}  # doc_path -> last error message
        self._stop_event: asyncio.Event | None = None

    def _load_template(self) -> str:
        template_path = Path(__file__).parent / "template.html"
        return template_path.read_text(encoding="utf-8")

    def _display_path(self, abs_path: Path) -> str:
        """Compute display path: relative if under launch_dir, else absolute."""
        try:
            return str(abs_path.relative_to(self.launch_dir))
        except ValueError:
            return str(abs_path)

    def _setup_routes(self):
        self.app.router.add_get("/", self._handle_index)
        self.app.router.add_get("/ws", self._handle_ws)
        self.app.router.add_get("/quarto-assets/{path:.+}", self._handle_quarto_assets)
        self.app.router.add_get("/api/list-dir", self._handle_list_dir)
        self.app.router.add_get("/api/export-pdf", self._handle_export_pdf)
        self.app.router.add_post("/api/relocate", self._handle_relocate)
        self.app.router.add_post("/api/shutdown", self._handle_shutdown)
        static_dir = Path(__file__).parent / "static"
        self.app.router.add_static("/static/", static_dir)

    async def _handle_quarto_assets(self, request):
        """Serve Quarto support files (CSS, JS, images) from <stem>_files/."""
        rel_path = request.match_info["path"]
        assets_dir = self.doc_path.parent / (self.doc_path.stem + "_files")
        file_path = (assets_dir / rel_path).resolve()
        if not file_path.is_relative_to(assets_dir.resolve()):
            return web.Response(status=403)
        if not file_path.is_file():
            return web.Response(status=404)
        return web.FileResponse(file_path)

    def _register_server_state(self, port: int):
        """Write _server key to state file."""
        from scholia.state import set_server

        set_server(self.doc_path, port=port, pid=os.getpid())

    def _clear_server_state(self):
        """Remove _server key from state file."""
        from scholia.state import clear_server

        try:
            clear_server(self.doc_path)
        except Exception:
            pass  # Best effort — file may already be deleted (ephemeral)

    def _ephemeral_cleanup(self):
        """Delete document and sidecars if in ephemeral mode."""
        if not self._ephemeral:
            return
        from scholia.files import remove_doc

        try:
            remove_doc(self.doc_path)
        except (FileNotFoundError, OSError):
            pass  # Already gone or permission issue

    async def _handle_index(self, request):
        file_param = request.query.get("file")
        if file_param:
            file_path = Path(file_param)
            if not file_path.is_absolute():
                file_path = self.launch_dir / file_path
            doc_path = file_path.resolve()
            display = self._display_path(doc_path)
        else:
            doc_path = self.doc_path
            display = self.display_path

        try:
            if _is_markdown(doc_path):
                sidenotes = _has_footnotes(doc_path.read_text(encoding="utf-8"))
                quarto_theme = request.query.get("quarto_theme", "scholia")
                page = await build_page(
                    doc_path,
                    self.template,
                    sidenotes=sidenotes,
                    display_path=display,
                    quarto_theme=quarto_theme,
                )
            else:
                force_raw = request.query.get("raw") == "1"
                page = _build_raw_page(
                    doc_path,
                    self.template,
                    display_path=display,
                    force=force_raw,
                )
        except (FileNotFoundError, OSError):
            import html as html_mod

            error_html = (
                "<h2>File not found</h2>" f"<p><code>{html_mod.escape(str(doc_path))}</code></p>"
            )
            page = _fill_template(
                self.template,
                title="Error — Scholia",
                html=error_html,
                doc_path=doc_path,
                display_path=display,
                readonly=True,
            )
        except (subprocess.CalledProcessError, RuntimeError) as e:
            import html as html_mod

            if isinstance(e, subprocess.CalledProcessError):
                detail = e.stderr or str(e)
            else:
                detail = str(e)
            detail = _strip_ansi(detail.strip())
            display_for_log = self._display_path(doc_path)
            print(
                f"\033[31m[scholia] Render error ({display_for_log}):\033[0m {detail}\n",
                file=sys.stderr,
            )
            error_html = "<h2>Render error</h2>" f"<p><code>{html_mod.escape(detail)}</code></p>"
            page = _fill_template(
                self.template,
                title="Error — Scholia",
                html=error_html,
                doc_path=doc_path,
                display_path=display,
                readonly=True,
            )

        return web.Response(text=page, content_type="text/html")

    async def _handle_list_dir(self, request):
        """Return directory listing as JSON."""
        dir_path = request.query.get("path", "")
        p = Path(dir_path).resolve()
        if not p.is_dir():
            return web.json_response({"error": f"Not a directory: {dir_path}"})

        entries = [{"name": "..", "type": "dir"}]
        dirs = []
        files = []
        for child in p.iterdir():
            if child.name.startswith("."):
                continue
            entry = {"name": child.name}
            is_link = child.is_symlink()
            if is_link:
                entry["link"] = str(child.resolve()).replace("\\", "/")
            if child.is_dir():
                entry["type"] = "dir"
                dirs.append(entry)
            else:
                entry["type"] = "file"
                files.append(entry)
        dirs.sort(key=lambda e: e["name"].lower())
        files.sort(key=lambda e: e["name"].lower())
        entries.extend(dirs)
        entries.extend(files)
        return web.json_response({"path": str(p).replace("\\", "/"), "entries": entries})

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
            if (
                "pdf" in stderr.lower()
                or "latex" in stderr.lower()
                or "xelatex" in stderr.lower()
                or "tectonic" in stderr.lower()
            ):
                return web.json_response(
                    {
                        "error": "PDF export requires a LaTeX engine (xelatex, tectonic, etc.).",
                        "fallback": "print",
                    },
                    status=422,
                )
            return web.json_response({"error": f"Export failed: {stderr}"}, status=500)

        return web.Response(
            body=pdf_bytes,
            content_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{doc_path.stem}.pdf"',
            },
        )

    async def _do_relocate(self, dest_path: Path, force: bool = False):
        """Shared relocate logic used by both /api/relocate and WS save_as.

        Moves files, updates watcher, re-keys ws_clients/ws_file, clears
        ephemeral flag, broadcasts to all clients. Returns the response dict.

        Raises FileExistsError or FileNotFoundError on failure.
        """
        from scholia.files import move_doc
        from scholia.state import set_server

        old_path = self.doc_path
        move_doc(str(old_path), str(dest_path), force=force)

        # Update watcher
        self._stop_watching(old_path)
        self.doc_path = dest_path
        self.display_path = str(dest_path)
        self._start_watching(dest_path)

        # Re-key ws_clients from old_path to dest_path
        clients = self.ws_clients.pop(old_path, set())
        self.ws_clients.setdefault(dest_path, set()).update(clients)
        for c in clients:
            self.ws_file[c] = dest_path

        # Update _server in the new state file
        set_server(dest_path, port=self.port, pid=os.getpid())

        # Clear ephemeral flag (file was promoted)
        self._ephemeral = False

        response = {
            "type": "relocated",
            "path": str(dest_path),
            "display_path": self._display_path(dest_path),
        }

        # Broadcast to all connected clients
        msg = json.dumps(response)
        for ws_set in self.ws_clients.values():
            for ws in ws_set:
                try:
                    await ws.send_str(msg)
                except Exception:
                    pass

        return response

    async def _handle_relocate(self, request):
        """POST /api/relocate — move document + sidecars to a new path."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        dest = body.get("to")
        force = body.get("force", False)
        if not dest:
            return web.json_response({"error": "Missing 'to' field"}, status=400)

        try:
            result = await self._do_relocate(Path(dest).expanduser().resolve(), force=force)
        except FileExistsError:
            return web.json_response({"error": f"Destination already exists: {dest}"}, status=409)
        except FileNotFoundError as e:
            return web.json_response({"error": str(e)}, status=404)

        return web.json_response({"path": result["path"]})

    async def _handle_ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self._handle_ws_message(msg.data, ws)
                elif msg.type == web.WSMsgType.ERROR:
                    break
        finally:
            doc = self.ws_file.pop(ws, None)
            self.ws_sidenotes.pop(ws, None)
            if doc and doc in self.ws_clients:
                self.ws_clients[doc].discard(ws)
                if not self.ws_clients[doc]:
                    del self.ws_clients[doc]
            if doc:
                self._stop_watching(doc)
        return ws

    async def _handle_ws_message(self, data: str, ws: web.WebSocketResponse):
        try:
            msg = json.loads(data)
            msg_type = msg["type"]
            if msg_type == "watch":
                file_path = Path(msg["file"]).resolve()
                self.ws_file[ws] = file_path
                if file_path not in self.ws_clients:
                    self.ws_clients[file_path] = set()
                self.ws_clients[file_path].add(ws)
                if self._loop:
                    self._start_watching(file_path)
                # Send stored render error if one exists for this document
                stored_error = self.render_errors.get(file_path)
                if stored_error:
                    await ws.send_json({"type": "render_error", "message": stored_error})
                return
            doc = self.ws_file.get(ws, self.doc_path)
            if msg_type == "new_comment":
                source_selector = None
                if msg.get("source_exact"):
                    source_selector = {
                        "exact": msg["source_exact"],
                        "prefix": msg.get("source_prefix", ""),
                        "suffix": msg.get("source_suffix", ""),
                    }
                append_comment(
                    doc,
                    exact=msg["exact"],
                    prefix=msg.get("prefix", ""),
                    suffix=msg.get("suffix", ""),
                    body_text=msg["body"],
                    creator=msg.get("creator", get_human_username()),
                    source_selector=source_selector,
                    via="browser",
                )
            elif msg_type == "reply":
                append_reply(
                    doc,
                    annotation_id=msg["annotation_id"],
                    body_text=msg["body"],
                    creator=msg.get("creator", get_human_username()),
                )
            elif msg_type == "edit_body":
                edit_body(
                    doc,
                    annotation_id=msg["annotation_id"],
                    new_text=msg["body"],
                )
            elif msg_type == "resolve":
                resolve(doc, msg["annotation_id"])
                mark_read(doc, msg["annotation_id"])
            elif msg_type == "unresolve":
                unresolve(doc, msg["annotation_id"])
            elif msg_type == "toggle_sidenotes":
                self.ws_sidenotes[ws] = msg["enabled"]
                await self._broadcast(doc, "doc")
            elif msg_type == "mark_read":
                mark_read(doc, msg["annotation_id"])
            elif msg_type == "mark_unread":
                mark_unread(doc, msg["annotation_id"])
            elif msg_type == "reanchor":
                source_selector = None
                if msg.get("source_exact"):
                    source_selector = {
                        "exact": msg["source_exact"],
                        "prefix": msg.get("source_prefix", ""),
                        "suffix": msg.get("source_suffix", ""),
                    }
                reanchor(
                    doc,
                    annotation_id=msg["annotation_id"],
                    exact=msg["exact"],
                    prefix=msg.get("prefix", ""),
                    suffix=msg.get("suffix", ""),
                    source_selector=source_selector,
                )
            elif msg_type == "save_as":
                dest = msg.get("path", "")
                if not dest:
                    await ws.send_json({"type": "error", "message": "Missing path"})
                    return
                try:
                    await self._do_relocate(Path(dest).expanduser().resolve())
                except FileExistsError:
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": f"Destination already exists: {dest}",
                        }
                    )
                except Exception as e:
                    await ws.send_json({"type": "error", "message": str(e)})
            elif msg_type == "render_markdown":
                bib, csl = _extract_bibliography(doc)
                html = await render_markdown_fragment(
                    msg["text"],
                    cwd=str(doc.parent),
                    bibliography=bib,
                    csl=csl,
                )
                await ws.send_json(
                    {
                        "type": "rendered_markdown",
                        "request_id": msg.get("request_id", ""),
                        "html": html,
                    }
                )
        except Exception as e:
            try:
                await ws.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass

    async def _broadcast(self, doc_path: Path, change_type: str):
        clients = self.ws_clients.get(doc_path, set())
        if not clients:
            return

        if change_type == "comments":
            comments = load_comments(doc_path)
            payload = json.dumps({"type": "comments_update", "comments": comments})
            closed = set()
            for ws in clients:
                try:
                    await ws.send_str(payload)
                except Exception:
                    closed.add(ws)
        else:
            default_sidenotes = _has_footnotes(doc_path.read_text(encoding="utf-8"))
            by_sidenotes: dict[bool, list] = {}
            for ws in clients:
                sn = self.ws_sidenotes.get(ws, default_sidenotes)
                by_sidenotes.setdefault(sn, []).append(ws)

            closed = set()
            # Notify clients that rendering has started (for progress indicator)
            start_payload = json.dumps({"type": "rendering_start"})
            for ws in clients:
                try:
                    await ws.send_str(start_payload)
                except Exception:
                    closed.add(ws)
            try:
                for sn_val, ws_list in by_sidenotes.items():
                    rendered, stderr = await render_doc(doc_path, sidenotes=sn_val)
                    if stderr.strip():
                        warn_display = self._display_path(doc_path)
                        clean_warn = _strip_ansi(stderr.strip())
                        pfx = f"\033[33m[scholia] Render warning ({warn_display}):\033[0m"
                        print(f"{pfx} {clean_warn}\n", file=sys.stderr)
                    if _is_quarto(doc_path):
                        # For Quarto, extract just <main> inner content for live update
                        main_match = re.search(
                            r"<main[^>]*>(.*)</main>", rendered, re.DOTALL | re.IGNORECASE
                        )
                        html = main_match.group(1) if main_match else rendered
                    else:
                        html = rendered
                    payload = json.dumps(
                        {
                            "type": "doc_update",
                            "html": html,
                            "sidenotes": sn_val,
                        }
                    )
                    for ws in ws_list:
                        try:
                            await ws.send_str(payload)
                        except Exception:
                            closed.add(ws)

                # Render succeeded — clear any stored error
                self.render_errors.pop(doc_path, None)

            except (subprocess.CalledProcessError, RuntimeError) as exc:
                # Extract the useful error message
                if isinstance(exc, subprocess.CalledProcessError):
                    err_msg = (exc.stderr or str(exc)).strip()
                else:
                    err_msg = str(exc).strip()

                display = self._display_path(doc_path)
                clean_msg = _strip_ansi(err_msg)
                print(
                    f"\033[31m[scholia] Render error ({display}):\033[0m {clean_msg}\n",
                    file=sys.stderr,
                )

                # Store and send to all clients
                self.render_errors[doc_path] = clean_msg
                error_payload = json.dumps({"type": "render_error", "message": clean_msg})
                for ws in clients:
                    try:
                        await ws.send_str(error_payload)
                    except Exception:
                        closed.add(ws)

        for ws in closed:
            clients.discard(ws)
            self.ws_file.pop(ws, None)
            self.ws_sidenotes.pop(ws, None)

    def _start_watching(self, doc_path: Path):
        """Start watching doc_path's parent directory if not already watched."""
        parent = doc_path.parent.resolve()
        if parent in self._observers:
            self._observer_refcount[parent] += 1
            return
        handler = _FileChangeHandler(self, self._loop)
        observer = Observer()
        observer.schedule(handler, str(parent), recursive=False)
        observer.start()
        self._observers[parent] = observer
        self._observer_refcount[parent] = 1

    def _stop_watching(self, doc_path: Path):
        """Decrement refcount; stop observer if it reaches zero."""
        parent = doc_path.parent.resolve()
        if parent not in self._observer_refcount:
            return
        self._observer_refcount[parent] -= 1
        if self._observer_refcount[parent] <= 0:
            observer = self._observers.pop(parent, None)
            del self._observer_refcount[parent]
            if observer:
                observer.stop()
                observer.join(timeout=1)

    def _on_file_change(self, doc_path: Path, change_type: str):
        """Debounced file change handler (called from watchdog thread via call_soon_threadsafe)."""
        key = (doc_path, change_type)
        handle = self._debounce_handles.get(key)
        if handle:
            handle.cancel()
        self._debounce_handles[key] = self._loop.call_later(
            0.2,
            lambda dp=doc_path, ct=change_type: asyncio.ensure_future(self._broadcast(dp, ct)),
        )

    async def _handle_shutdown(self, request: web.Request) -> web.Response:
        """POST /api/shutdown — stop the server gracefully."""
        if self._stop_event is not None:
            self._stop_event.set()
        return web.json_response({"status": "stopping"})

    async def start(self):
        self._loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        self._stop_event = stop_event

        def _request_stop():
            if not stop_event.is_set():
                stop_event.set()
            else:
                # Second Ctrl-C: force exit
                raise SystemExit(0)

        for sig in (signal.SIGINT, signal.SIGTERM):
            self._loop.add_signal_handler(sig, _request_stop)

        # Start watchdog for the initial document
        self._start_watching(self.doc_path)

        # Start web server
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        try:
            await site.start()
        except OSError:
            if self.port != 0:
                # Port in use — retry with OS-assigned port
                site = web.TCPSite(runner, self.host, 0)
                await site.start()
                self.port = 0
            else:
                raise

        if self.port == 0:
            actual_port = site._server.sockets[0].getsockname()[1]
        else:
            actual_port = self.port
        self.port = actual_port  # store resolved port for _do_relocate etc.
        url = f"http://{self.host}:{actual_port}"
        print(f"Scholia serving {self.doc_path.name} at {url}")
        print("Press Ctrl+C to stop")

        self._register_server_state(actual_port)

        if self._open_browser:
            import webbrowser

            webbrowser.open(url)

        try:
            await stop_event.wait()
        finally:
            # Close all WebSocket connections so runner.cleanup() doesn't block
            for clients in list(self.ws_clients.values()):
                for ws in list(clients):
                    await ws.close()
            self.ws_clients.clear()
            self.ws_file.clear()
            self.ws_sidenotes.clear()

            # Stop all observers
            for observer in self._observers.values():
                observer.stop()
            for observer in self._observers.values():
                observer.join(timeout=1)
            self._observers.clear()
            self._observer_refcount.clear()

            self._clear_server_state()
            self._ephemeral_cleanup()

        await runner.cleanup()
