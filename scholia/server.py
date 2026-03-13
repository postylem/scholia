"""Asyncio server: Pandoc render, file watch, WebSocket push."""

import asyncio
import json
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
    load_comments,
)


def _check_pandoc():
    """Verify Pandoc is installed."""
    if shutil.which("pandoc") is None:
        raise RuntimeError(
            "Pandoc not found. Install it from https://pandoc.org/installing.html"
        )


def _render_pandoc_sync(doc_path: Path) -> str:
    """Render markdown to HTML fragment using Pandoc (blocking)."""
    result = subprocess.run(
        [
            "pandoc",
            "--katex",
            "--highlight-style=pygments",
            "--from=markdown+tex_math_single_backslash",
            "--to=html",
        ],
        input=doc_path.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


async def render_pandoc(doc_path: Path) -> str:
    """Render markdown to HTML fragment without blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _render_pandoc_sync, doc_path)


async def build_page(doc_path: Path, template: str) -> str:
    """Build full HTML page from template + rendered markdown + comments."""
    html = await render_pandoc(doc_path)
    comments = load_comments(doc_path)
    page = template.replace("{{PANDOC_HTML}}", html)
    page = page.replace("{{COMMENTS_JSON}}", json.dumps(comments))
    return page


class _FileChangeHandler(FileSystemEventHandler):
    """Watch .md and .scholia.jsonl for changes."""

    def __init__(self, doc_path: Path, loop: asyncio.AbstractEventLoop, callback):
        self.doc_path = doc_path.resolve()
        self.scholia_path = annotation_path(doc_path).resolve()
        self.loop = loop
        self.callback = callback

    def on_modified(self, event):
        changed = Path(event.src_path).resolve()
        if changed == self.doc_path:
            self.loop.call_soon_threadsafe(self.callback, "doc")
        elif changed == self.scholia_path:
            self.loop.call_soon_threadsafe(self.callback, "comments")


class ScholiaServer:
    def __init__(self, doc_path: str, host: str = "127.0.0.1", port: int = 8088):
        _check_pandoc()
        self.doc_path = Path(doc_path).resolve()
        if not self.doc_path.exists():
            raise FileNotFoundError(f"Document not found: {self.doc_path}")
        self.host = host
        self.port = port
        self.ws_clients: set[web.WebSocketResponse] = set()
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
        page = await build_page(self.doc_path, self.template)
        return web.Response(text=page, content_type="text/html")

    async def _handle_ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws_clients.add(ws)
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self._handle_ws_message(msg.data)
                elif msg.type == web.WSMsgType.ERROR:
                    break
        finally:
            self.ws_clients.discard(ws)
        return ws

    async def _handle_ws_message(self, data: str):
        try:
            msg = json.loads(data)
            if msg["type"] == "new_comment":
                append_comment(
                    self.doc_path,
                    exact=msg["exact"],
                    prefix=msg.get("prefix", ""),
                    suffix=msg.get("suffix", ""),
                    body_text=msg["body"],
                    creator="human",
                )
            elif msg["type"] == "reply":
                append_reply(
                    self.doc_path,
                    annotation_id=msg["annotation_id"],
                    body_text=msg["body"],
                    creator=msg.get("creator", "human"),
                )
        except Exception as e:
            print(f"warning: bad WebSocket message: {e}")

    async def _broadcast(self, msg_type: str):
        if msg_type == "doc":
            html = await render_pandoc(self.doc_path)
            payload = json.dumps({"type": "doc_update", "html": html})
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
