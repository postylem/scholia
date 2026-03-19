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


def _has_footnotes(md_text: str) -> bool:
    """Check if markdown contains footnote syntax ([^...] or ^[...])."""
    return bool(re.search(r"\[\^|\^\[", md_text))


def _render_pandoc_sync(doc_path: Path, sidenotes: bool = False) -> str:
    """Render markdown to HTML fragment using Pandoc (blocking)."""
    md_text = doc_path.read_text(encoding="utf-8")
    has_own_csl = re.search(r"^csl:", md_text, re.MULTILINE) is not None

    cmd = [
        "pandoc",
        "--katex",
    ]
    if _HAS_CROSSREF:
        cmd.extend(["--filter", "pandoc-crossref"])
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
    md_text = doc_path.read_text(encoding="utf-8")
    title = _extract_title(md_text)
    comments = load_comments(doc_path)
    state = load_state(doc_path)
    page = template.replace("{{TITLE}}", title)
    page = page.replace("{{PANDOC_HTML}}", html)
    page = page.replace("{{CREATOR_NAME}}", json.dumps(get_human_username()))
    page = page.replace("{{DOC_PATH}}", json.dumps(display_path or str(doc_path)))
    page = page.replace("{{DOC_FULLPATH}}", json.dumps(str(doc_path)))
    page = page.replace("{{SIDENOTES_ENABLED}}", json.dumps(sidenotes))
    page = page.replace("{{COMMENTS_JSON}}", json.dumps(comments))
    page = page.replace("{{STATE_JSON}}", json.dumps(state))
    return page


class _FileChangeHandler(FileSystemEventHandler):
    """Watch .md and .scholia.jsonl for changes."""

    def __init__(self, doc_path: Path, loop: asyncio.AbstractEventLoop, callback):
        self.doc_path = doc_path.resolve()
        self.scholia_path = annotation_path(doc_path).resolve()
        self.loop = loop
        self.callback = callback

    def _check_path(self, path: Path):
        resolved = path.resolve()
        if resolved == self.doc_path:
            self.loop.call_soon_threadsafe(self.callback, "doc")
        elif resolved == self.scholia_path:
            self.loop.call_soon_threadsafe(self.callback, "comments")

    def on_modified(self, event):
        self._check_path(Path(event.src_path))

    def on_created(self, event):
        self._check_path(Path(event.src_path))

    def on_moved(self, event):
        # Atomic writes: temp file renamed over target
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
        self.ws_clients: set[web.WebSocketResponse] = set()
        # Auto-detect sidenotes: on if doc has footnotes
        md_text = self.doc_path.read_text(encoding="utf-8")
        self.sidenotes_enabled = _has_footnotes(md_text)
        self.template = self._load_template()
        self.app = web.Application()
        self._setup_routes()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._debounce_handles: dict[str, asyncio.TimerHandle] = {}

    def _load_template(self) -> str:
        template_path = Path(__file__).parent / "template.html"
        return template_path.read_text(encoding="utf-8")

    def _setup_routes(self):
        self.app.router.add_get("/", self._handle_index)
        self.app.router.add_get("/ws", self._handle_ws)
        static_dir = Path(__file__).parent / "static"
        self.app.router.add_static("/static/", static_dir)

    async def _handle_index(self, request):
        page = await build_page(
            self.doc_path, self.template,
            sidenotes=self.sidenotes_enabled,
            display_path=self.display_path,
        )
        return web.Response(text=page, content_type="text/html")

    async def _handle_ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws_clients.add(ws)
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self._handle_ws_message(msg.data, ws)
                elif msg.type == web.WSMsgType.ERROR:
                    break
        finally:
            self.ws_clients.discard(ws)
        return ws

    async def _handle_ws_message(self, data: str, ws: web.WebSocketResponse):
        try:
            msg = json.loads(data)
            msg_type = msg["type"]
            if msg_type == "new_comment":
                append_comment(
                    self.doc_path,
                    exact=msg["exact"],
                    prefix=msg.get("prefix", ""),
                    suffix=msg.get("suffix", ""),
                    body_text=msg["body"],
                    creator=msg.get("creator", get_human_username()),
                )
            elif msg_type == "reply":
                append_reply(
                    self.doc_path,
                    annotation_id=msg["annotation_id"],
                    body_text=msg["body"],
                    creator=msg.get("creator", get_human_username()),
                )
            elif msg_type == "edit_body":
                edit_body(
                    self.doc_path,
                    annotation_id=msg["annotation_id"],
                    new_text=msg["body"],
                )
            elif msg_type == "resolve":
                resolve(self.doc_path, msg["annotation_id"])
                mark_read(self.doc_path, msg["annotation_id"])
            elif msg_type == "unresolve":
                unresolve(self.doc_path, msg["annotation_id"])
            elif msg_type == "toggle_sidenotes":
                self.sidenotes_enabled = msg["enabled"]
                await self._broadcast("doc")
            elif msg_type == "mark_read":
                mark_read(self.doc_path, msg["annotation_id"])
            elif msg_type == "mark_unread":
                mark_unread(self.doc_path, msg["annotation_id"])
            elif msg_type == "reanchor":
                reanchor(
                    self.doc_path,
                    annotation_id=msg["annotation_id"],
                    exact=msg["exact"],
                    prefix=msg.get("prefix", ""),
                    suffix=msg.get("suffix", ""),
                )
            elif msg_type == "render_markdown":
                bib, csl = _extract_bibliography(self.doc_path)
                html = await render_markdown_fragment(
                    msg["text"],
                    cwd=str(self.doc_path.parent),
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

    async def _broadcast(self, msg_type: str):
        if msg_type == "doc":
            html = await render_pandoc(
                self.doc_path, sidenotes=self.sidenotes_enabled
            )
            payload = json.dumps({
                "type": "doc_update",
                "html": html,
                "sidenotes": self.sidenotes_enabled,
            })
        else:
            comments = load_comments(self.doc_path)
            payload = json.dumps({"type": "comments_update", "comments": comments})

        closed = set()
        for ws in self.ws_clients:
            try:
                await ws.send_str(payload)
            except Exception:
                closed.add(ws)
        self.ws_clients -= closed

    def _on_file_change(self, change_type: str):
        """Debounced file change handler (called from watchdog thread via call_soon_threadsafe)."""
        handle = self._debounce_handles.get(change_type)
        if handle:
            handle.cancel()
        self._debounce_handles[change_type] = self._loop.call_later(
            0.2, lambda: asyncio.ensure_future(self._broadcast(change_type))
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

        # Start watchdog
        handler = _FileChangeHandler(self.doc_path, self._loop, self._on_file_change)
        observer = Observer()
        observer.schedule(handler, str(self.doc_path.parent), recursive=False)
        observer.start()

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
        for ws in list(self.ws_clients):
            await ws.close()
        self.ws_clients.clear()

        observer.stop()
        observer.join(timeout=1)
        await runner.cleanup()
