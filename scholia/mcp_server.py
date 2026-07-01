"""``scholia mcp`` — an MCP server that lets an AI agent wait for a browser review.

The agent calls the ``request_review`` tool after it has written or revised a
document open in scholia. The tool blocks until the human clicks "Send to AI"
(or a per-comment "Send to AI") in the sidebar, then returns the comments to
address. The agent fixes them with the normal CLI (``scholia reply`` /
``scholia resolve`` / editing the file) and may call ``request_review`` again to
wait for the next round, until the human clicks "Send & finish".

How it connects: the live review session lives in the running ``scholia view``
server, discovered through the document's ``.scholia.state.json`` ``_server``
key (the same mechanism ``scholia mv`` uses to reach a running server). The MCP
process talks to it over localhost HTTP; the browser talks to it over the
WebSocket. If no view server is running, the tool starts one (opening the
browser) before waiting.

The "agent long-polls a server-held session that the browser resolves" handshake
is adapted from md-redline (https://github.com/dejuknow/md-redline, MIT), which
pioneered this review loop for Markdown. Scholia contributes its own W3C
annotation storage, Pandoc rendering, and recoverable anchoring; only the
rendezvous pattern is borrowed.

The ``mcp`` package is an optional dependency (``pip install 'scholia[mcp]'``);
it is imported lazily in :func:`build_server` so the rest of this module — the
HTTP/formatting helpers — stays importable (and testable) without it.
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import aiohttp

from scholia.comments import is_general, load_comments, short_id_map
from scholia.context import format_orphan_context, locate_anchor, render_doc_plain
from scholia.state import get_server

# How long each long-poll HTTP request waits before the server returns
# "pending" (kept short so progress is reported and disconnects are noticed).
CHUNK_SECONDS = 25.0
# Overall soft cap for a single request_review call. When exceeded, the tool
# returns a "still waiting" result so the agent can re-invoke (resuming the same
# session) rather than holding one tool call open indefinitely. Configurable for
# long author absences.
OVERALL_TIMEOUT = float(os.environ.get("SCHOLIA_REVIEW_TIMEOUT", "1800"))


def _server_base_url(doc_path: Path) -> str | None:
    """Return the base URL of a running view server for *doc_path*, or None."""
    info = get_server(doc_path)
    if not info or "port" not in info:
        return None
    return f"http://127.0.0.1:{info['port']}"


async def _is_healthy(base: str) -> bool:
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(base + "/", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                return resp.status < 500
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return False


async def _ensure_server(doc_path: Path) -> str:
    """Return the base URL of a view server for *doc_path*, starting one if needed.

    Mirrors ``scholia mv``'s discovery: read the ``_server`` state key, and if no
    healthy server is recorded, launch ``scholia view <doc>`` (which opens the
    browser) and wait for it to come up. Raises RuntimeError on failure.
    """
    base = _server_base_url(doc_path)
    if base and await _is_healthy(base):
        return base

    subprocess.Popen(
        [sys.executable, "-m", "scholia", "view", str(doc_path)],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        await asyncio.sleep(0.4)
        base = _server_base_url(doc_path)
        if base and await _is_healthy(base):
            return base
    raise RuntimeError(
        f"Could not start a scholia view server for {doc_path}. "
        f"Run `scholia view {doc_path}` yourself, then call request_review again."
    )


def _format_review_payload(
    doc_path: Path, comment_ids: list[str], action: str, instruction: str
) -> str:
    """Render the submitted comments into an actionable block for the agent.

    Mirrors ``scholia list`` output (file reference, heading breadcrumb, context
    lines, the thread) so the agent gets the same context it would on the CLI.
    """
    comments = load_comments(doc_path)
    id_map = short_id_map(doc_path)
    by_id = {c["id"]: c for c in comments}
    rendered = render_doc_plain(doc_path)
    selected = [by_id[cid] for cid in comment_ids if cid in by_id]

    lines: list[str] = []
    n = len(selected)
    if n:
        lines.append(
            f"The human sent {n} comment{'s' if n != 1 else ''} to address in {doc_path}:"
        )
    else:
        lines.append(f"The human ended the review of {doc_path} without selecting comments.")
    lines.append("")

    for ann in selected:
        target = ann.get("target", {})
        selector = target.get("scholia:sourceSelector") or target.get("selector", {})
        short = id_map.get(ann["id"], ann["id"])
        lines.append(short)
        if is_general(ann):
            lines.append("  (general comment - about the whole document)")
        else:
            ctx = locate_anchor(doc_path, selector, rendered_text=rendered)
            if ctx["found"]:
                loc = f"{doc_path}:{ctx['line']}:{ctx['col']}"
                if ctx["end_line"] != ctx["line"]:
                    loc += f"-{ctx['end_line']}:{ctx['end_col']}"
                elif ctx["end_col"] != ctx["col"] + 1:
                    loc += f"-{ctx['end_col']}"
                lines.append(f"  {loc}")
                if ctx.get("heading"):
                    lines.append(f"  in {ctx['heading']}")
                for cline in ctx.get("context_lines") or []:
                    lines.append(cline)
            else:
                # Orphaned: show the original prefix/exact/suffix the comment was
                # made against, so the agent still knows what it referred to.
                lines.append("  (anchor text not found in current document — orphaned)")
                lines.append("  original context:")
                lines.extend(format_orphan_context(selector))
        lines.append("")
        for b in ann.get("body", []):
            who = (b.get("creator") or {}).get("name", "?")
            lines.append(f"  [{who}] {b.get('value', '')}")
        lines.append("")

    if instruction:
        lines.append(f"Note from the human: {instruction}")
        lines.append("")

    if action == "finish":
        lines.append(
            "The human marked the review COMPLETE. Address these final items (edit the "
            "document and/or reply with `scholia reply <doc> <id> ... --author-ai-model "
            "<model>` and `scholia resolve <doc> <id>`), then stop — do NOT call "
            "request_review again."
        )
    else:
        lines.append(
            "Address each item (edit the document and/or use `scholia reply <doc> <id> "
            '"..." --author-ai-model <model>` and `scholia resolve <doc> <id>`). The '
            "human sees your replies live. When done, call request_review again with the "
            "same doc to wait for the next round. General comments refer to the whole "
            "document - read the document as needed and answer as you would in chat."
        )
    return "\n".join(lines)


async def _report_progress(ctx, progress: float, total: float) -> None:
    if ctx is None:
        return
    try:
        await ctx.report_progress(
            progress=progress, total=total, message="waiting for your review…"
        )
    except Exception:
        pass


async def _await_submission(
    http: "aiohttp.ClientSession",
    base: str,
    session_id: str,
    ctx=None,
    chunk: float = CHUNK_SECONDS,
    overall: float = OVERALL_TIMEOUT,
) -> dict:
    """Long-poll the view server until the human submits, cancels, or we time out.

    Returns the server's wait payload, or a synthetic
    ``{"status": "timeout"|"unreachable"}`` dict.
    """
    elapsed = 0.0
    fails = 0
    while True:
        try:
            async with http.get(
                base + "/api/review/wait",
                params={"session_id": session_id, "timeout": str(chunk)},
                timeout=aiohttp.ClientTimeout(total=chunk + 20),
            ) as resp:
                if resp.status == 404:
                    return {"status": "unknown"}
                data = await resp.json()
            fails = 0
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            fails += 1
            if fails >= 3:
                return {"status": "unreachable"}
            await asyncio.sleep(1.0)
            continue

        status = data.get("status")
        if status in ("submitted", "aborted", "unknown"):
            return data
        # pending — keep waiting
        elapsed += chunk
        await _report_progress(ctx, elapsed, overall)
        if elapsed >= overall:
            return {"status": "timeout"}


async def _run_request_review(doc: str, instruction: str = "", ctx=None) -> str:
    """Core of the request_review tool (separated from FastMCP for testing)."""
    doc_path = Path(doc).expanduser().resolve()
    if not doc_path.exists():
        return f"Error: document not found: {doc_path}"

    try:
        base = await _ensure_server(doc_path)
    except RuntimeError as e:
        return f"Error: {e}"

    async with aiohttp.ClientSession() as http:
        try:
            async with http.post(
                base + "/api/review/start",
                json={"doc": str(doc_path), "instruction": instruction},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                start = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return f"Error: scholia view server at {base} is not reachable."
        session_id = start["session_id"]

        if ctx is not None:
            try:
                await ctx.info(
                    f"Waiting for your review in the browser ({base}). "
                    "Use 'Send to AI' in the scholia sidebar."
                )
            except Exception:
                pass

        result = await _await_submission(http, base, session_id, ctx=ctx)

    status = result.get("status")
    if status == "submitted":
        return _format_review_payload(
            doc_path,
            result.get("comment_ids", []),
            result.get("action", "submit"),
            result.get("instruction", ""),
        )
    if status == "aborted":
        return (
            "The human cancelled the review without sending comments. Continue with your "
            "prior task, or ask them how they'd like to proceed."
        )
    if status == "timeout":
        return (
            f"No review submitted yet. The human may still be reviewing in the browser "
            f"({base}). Call request_review again with doc='{doc}' to keep waiting (it "
            "resumes the same session), or do other work and check back."
        )
    if status == "unreachable":
        return (
            f"Lost contact with the scholia view server for {doc}. Is it still running? "
            "Re-run `scholia view` and try again."
        )
    return (
        f"The review session for {doc} is no longer active (the browser may have ended it). "
        "Call request_review again to start a new one if needed."
    )


def build_server():
    """Construct the FastMCP server. Imports ``mcp`` lazily (optional dep)."""
    from mcp.server.fastmcp import Context, FastMCP

    mcp = FastMCP("scholia")

    @mcp.tool()
    async def request_review(doc: str, instruction: str = "", ctx: Context = None) -> str:
        """Open *doc* for the human to review in the scholia browser and WAIT for their comments.

        Call this after you have written or revised a Markdown document that the
        human is viewing with scholia, when you want them to review it and tell
        you what to change — without them switching back to the terminal.

        This BLOCKS until the human clicks "Send to AI" (send selected/all open
        comments) or "Send & finish" in the scholia sidebar, then returns those
        comments with document context, ready for you to address. They can also
        send a single comment via its per-comment "Send to AI" button.

        Args:
            doc: Path to the Markdown document (a `scholia view` server is
                started for it if one isn't already running).
            instruction: Optional note shown to the human about what to review
                (e.g. "Please check the proof in section 3").

        After addressing the returned comments (edit the file and/or use
        `scholia reply` / `scholia resolve`), call request_review again with the
        same `doc` to wait for the next round — unless the result says the human
        marked the review complete.
        """
        return await _run_request_review(doc, instruction, ctx)

    return mcp


def run() -> None:
    """Run the MCP server over stdio (blocks)."""
    build_server().run(transport="stdio")
