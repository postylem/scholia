"""Asyncio server: Pandoc render, file watch, WebSocket push."""

import asyncio
import json
import re
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
    get_default_creator,
    load_comments,
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
        "--citeproc",
        "--section-divs",
        "--syntax-highlighting=pygments",
        "--metadata=link-citations:true",
        "--from=markdown+tex_math_single_backslash",
        "--to=html5",
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


async def build_page(doc_path: Path, template: str, sidenotes: bool = False) -> str:
    """Build full HTML page from template + rendered markdown + comments."""
    html = await render_pandoc(doc_path, sidenotes=sidenotes)
    md_text = doc_path.read_text(encoding="utf-8")
    title = _extract_title(md_text)
    comments = load_comments(doc_path)
    state = load_state(doc_path)
    page = template.replace("{{TITLE}}", title)
    page = page.replace("{{PANDOC_HTML}}", html)
    page = page.replace("{{CREATOR_NAME}}", json.dumps(get_default_creator()))
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
            self.doc_path, self.template, sidenotes=self.sidenotes_enabled
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
                    creator=msg.get("creator", get_default_creator()),
                )
            elif msg_type == "reply":
                append_reply(
                    self.doc_path,
                    annotation_id=msg["annotation_id"],
                    body_text=msg["body"],
                    creator=msg.get("creator", get_default_creator()),
                )
            elif msg_type == "resolve":
                resolve(self.doc_path, msg["annotation_id"])
            elif msg_type == "unresolve":
                unresolve(self.doc_path, msg["annotation_id"])
            elif msg_type == "toggle_sidenotes":
                self.sidenotes_enabled = msg["enabled"]
                await self._broadcast("doc")
            elif msg_type == "mark_read":
                mark_read(self.doc_path, msg["annotation_id"])
            elif msg_type == "mark_unread":
                mark_unread(self.doc_path, msg["annotation_id"])
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

        # Start watchdog
        handler = _FileChangeHandler(self.doc_path, self._loop, self._on_file_change)
        observer = Observer()
        observer.schedule(handler, str(self.doc_path.parent), recursive=False)
        observer.start()

        # Start web server
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        url = f"http://{self.host}:{self.port}"
        print(f"Scholia serving {self.doc_path.name} at {url}")
        print("Press Ctrl+C to stop")

        try:
            await asyncio.Event().wait()
        finally:
            observer.stop()
            observer.join()
            await runner.cleanup()
