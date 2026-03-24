"""Asyncio server: Pandoc render, file watch, WebSocket push."""

import asyncio
import json
import re
import signal
import shutil
import subprocess
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
        raise RuntimeError(
            "Pandoc not found. Install it from https://pandoc.org/installing.html"
        )


_SIDENOTE_FILTER = str(Path(__file__).parent / "filters" / "sidenote.lua")
_DEFAULT_CSL = str(Path(__file__).parent / "static" / "apa.csl")
_FRAGMENT_TEMPLATE = str(Path(__file__).parent / "pandoc-fragment.html")
_HAS_CROSSREF = shutil.which("pandoc-crossref") is not None
_MARKDOWN_EXTENSIONS = {".md", ".markdown", ".qmd", ".rmd"}


def _is_markdown(path: Path) -> bool:
    return path.suffix.lower() in _MARKDOWN_EXTENSIONS


def _has_footnotes(md_text: str) -> bool:
    """Check if markdown contains footnote syntax ([^...] or ^[...])."""
    return bool(re.search(r"\[\^|\^\[", md_text))


def _render_pandoc_sync(doc_path: Path, sidenotes: bool = False) -> str:
    """Render markdown to HTML fragment using Pandoc (blocking)."""
    md_text = doc_path.read_text(encoding="utf-8")
    has_own_csl = re.search(r"^csl:", md_text, re.MULTILINE) is not None
    number_sections = re.search(r"^number-sections:\s*true", md_text, re.MULTILINE) is not None

    # Load external LaTeX macros file if specified in frontmatter
    macros_match = re.search(r"^macros:\s*['\"]?(.+?)['\"]?\s*$", md_text, re.MULTILINE)
    if macros_match:
        macros_path = doc_path.parent / macros_match.group(1).strip()
        if macros_path.is_file():
            macros_content = macros_path.read_text(encoding="utf-8")
            # Insert after YAML frontmatter so Pandoc parses macros at block level
            fm_end = re.search(
                r"\A---\s*\n.*?^(---|\.\.\.)\s*$", md_text, re.MULTILINE | re.DOTALL
            )
            if fm_end:
                pos = fm_end.end()
                md_text = md_text[:pos] + "\n" + macros_content + "\n" + md_text[pos:]

    cmd = [
        "pandoc",
        "--katex",
    ]
    if _HAS_CROSSREF:
        cmd.extend([
            "--filter", "pandoc-crossref",
            "--metadata=linkReferences:true",
            "--metadata=secPrefix:§",
        ])
    cmd += [
        "--citeproc",
        "--section-divs",
        "--syntax-highlighting=pygments",
        "--metadata=link-citations:true",
        "--from=markdown+tex_math_single_backslash",
        "--to=html5",
        "--template=" + _FRAGMENT_TEMPLATE,
    ]
    if sidenotes:
        cmd.extend(["--lua-filter", _SIDENOTE_FILTER])
    if not has_own_csl:
        cmd.extend(["--csl", _DEFAULT_CSL])
    if number_sections:
        cmd.append("--number-sections")

    result = subprocess.run(
        cmd,
        input=md_text,
        capture_output=True,
        text=True,
        check=True,
        cwd=str(doc_path.parent),  # resolve relative bibliography paths
    )
    return result.stdout


async def render_pandoc(doc_path: Path, sidenotes: bool = False) -> str:
    """Render markdown to HTML fragment without blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _render_pandoc_sync, doc_path, sidenotes)


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
    text: str, cwd: str = ".", bibliography: str | None = None, csl: str | None = None,
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
        cmd, input=text, capture_output=True, text=True, check=True, cwd=cwd,
    )
    return result.stdout


async def render_markdown_fragment(
    text: str, cwd: str = ".", bibliography: str | None = None, csl: str | None = None,
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


async def build_page(
    doc_path: Path, template: str, sidenotes: bool = False, display_path: str = ""
) -> str:
    """Build full HTML page from template + rendered markdown + comments."""
    html = await render_pandoc(doc_path, sidenotes=sidenotes)
    title = _extract_title(doc_path.read_text(encoding="utf-8"))
    return _fill_template(
        template, title=title, html=html, doc_path=doc_path,
        display_path=display_path, sidenotes=sidenotes,
        comments=load_comments(doc_path), state=load_state(doc_path),
    )


def _is_binary(path: Path) -> bool:
    """Heuristic: file is binary if the first 8KB contains null bytes."""
    try:
        chunk = path.read_bytes()[:8192]
        return b"\x00" in chunk
    except OSError:
        return False


def _fill_template(
    template: str, *, title: str, html: str, doc_path: Path,
    display_path: str = "", sidenotes: bool = False,
    comments: list | None = None, state: dict | None = None,
    readonly: bool = False,
) -> str:
    """Fill the page template with the given content and metadata."""
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
    return page


def _build_raw_page(
    doc_path: Path, template: str, display_path: str = "", force: bool = False,
) -> str:
    """Build HTML page for a non-markdown file, displayed as raw text."""
    import html as html_mod
    if not force and _is_binary(doc_path):
        content = (
            '<p>This appears to be a binary file.</p>'
            f'<p><a href="/?file={html_mod.escape(display_path or str(doc_path))}&amp;raw=1">'
            'Display anyway</a></p>'
        )
        return _fill_template(
            template, title=doc_path.name + " — Scholia", html=content,
            doc_path=doc_path, display_path=display_path, readonly=True,
        )
    raw = doc_path.read_text(encoding="utf-8", errors="replace")
    escaped = html_mod.escape(raw)
    content = f'<pre class="scholia-raw-file"><code>{escaped}</code></pre>'
    return _fill_template(
        template, title=doc_path.name + " — Scholia", html=content,
        doc_path=doc_path, display_path=display_path,
        comments=load_comments(doc_path), state=load_state(doc_path),
    )


class _FileChangeHandler(FileSystemEventHandler):
    """Watch for changes to any registered doc or its .scholia.jsonl."""

    def __init__(self, server: 'ScholiaServer', loop: asyncio.AbstractEventLoop):
        self.server = server
        self.loop = loop

    def _check_path(self, path: Path):
        resolved = path.resolve()
        for doc_path in list(self.server.ws_clients.keys()):
            if resolved == doc_path:
                self.loop.call_soon_threadsafe(
                    self.server._on_file_change, doc_path, "doc"
                )
            elif resolved == annotation_path(doc_path).resolve():
                self.loop.call_soon_threadsafe(
                    self.server._on_file_change, doc_path, "comments"
                )

    def on_modified(self, event):
        self._check_path(Path(event.src_path))

    def on_created(self, event):
        self._check_path(Path(event.src_path))

    def on_moved(self, event):
        self._check_path(Path(event.dest_path))


class ScholiaServer:
    def __init__(self, doc_path: str, host: str = "127.0.0.1", port: int = 8088):
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
        self.app.router.add_get("/api/list-dir", self._handle_list_dir)
        static_dir = Path(__file__).parent / "static"
        self.app.router.add_static("/static/", static_dir)

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
                page = await build_page(
                    doc_path, self.template,
                    sidenotes=sidenotes,
                    display_path=display,
                )
            else:
                force_raw = request.query.get("raw") == "1"
                page = _build_raw_page(
                    doc_path, self.template, display_path=display, force=force_raw,
                )
        except (FileNotFoundError, OSError) as e:
            import html as html_mod
            error_html = (
                '<h2>File not found</h2>'
                f'<p><code>{html_mod.escape(str(doc_path))}</code></p>'
            )
            page = _fill_template(
                self.template, title="Error — Scholia", html=error_html,
                doc_path=doc_path, display_path=display, readonly=True,
            )
        except subprocess.CalledProcessError as e:
            import html as html_mod
            error_html = (
                '<h2>Render error</h2>'
                f'<p><code>{html_mod.escape(str(e.stderr or str(e)))}</code></p>'
            )
            page = _fill_template(
                self.template, title="Error — Scholia", html=error_html,
                doc_path=doc_path, display_path=display, readonly=True,
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
                return
            doc = self.ws_file.get(ws, self.doc_path)
            if msg_type == "new_comment":
                append_comment(
                    doc,
                    exact=msg["exact"],
                    prefix=msg.get("prefix", ""),
                    suffix=msg.get("suffix", ""),
                    body_text=msg["body"],
                    creator=msg.get("creator", get_human_username()),
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
                reanchor(
                    doc,
                    annotation_id=msg["annotation_id"],
                    exact=msg["exact"],
                    prefix=msg.get("prefix", ""),
                    suffix=msg.get("suffix", ""),
                )
            elif msg_type == "render_markdown":
                bib, csl = _extract_bibliography(doc)
                html = await render_markdown_fragment(
                    msg["text"],
                    cwd=str(doc.parent),
                    bibliography=bib,
                    csl=csl,
                )
                await ws.send_json({
                    "type": "rendered_markdown",
                    "request_id": msg.get("request_id", ""),
                    "html": html,
                })
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
            for sn_val, ws_list in by_sidenotes.items():
                html = await render_pandoc(doc_path, sidenotes=sn_val)
                payload = json.dumps({
                    "type": "doc_update",
                    "html": html,
                    "sidenotes": sn_val,
                })
                for ws in ws_list:
                    try:
                        await ws.send_str(payload)
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
            0.2, lambda dp=doc_path, ct=change_type: asyncio.ensure_future(self._broadcast(dp, ct))
        )

    async def start(self):
        self._loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

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
        url = f"http://{self.host}:{actual_port}"
        print(f"Scholia serving {self.doc_path.name} at {url}")
        print("Press Ctrl+C to stop")

        import webbrowser
        webbrowser.open(url)

        await stop_event.wait()

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

        await runner.cleanup()
