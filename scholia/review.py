"""In-memory review sessions: the human → AI "send to review" handshake.

A *review session* links a waiting AI agent (which long-polls over HTTP from the
``scholia mcp`` process) to the browser (which submits comments over the
WebSocket). The agent and the browser never talk to each other directly — they
rendezvous on a session object owned by the running ``scholia view`` server:

    agent  ──POST /api/review/start──▶  server creates ReviewSession
    agent  ──GET  /api/review/wait ──▶  await session.wait()  ┐ blocks
    human  ──WS   review_submit    ──▶  session.submit(...)   ┘ unblocks
    agent  ◀── comments to address ──

Because the session lives in the view server (not the short-lived MCP process),
it survives across tool calls: a re-invoked ``request_review`` rejoins the same
pending session.

The rendezvous design — a server-held session the agent long-polls and the
browser resolves — is adapted from md-redline (https://github.com/dejuknow/md-redline),
an MIT-licensed tool that pioneered this loop for Markdown review. Scholia keeps
its own W3C-annotation storage and recoverable anchoring; only the handshake
pattern is borrowed.
"""

import asyncio
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

# A session is "active" (shown as a banner in the browser) while the agent is
# either waiting for input or working on a just-submitted batch.
ACTIVE_STATUSES = ("waiting", "working")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewSession:
    """A single agent's review request for one document.

    Submissions from the browser are buffered in a deque and handed to the
    waiting agent one batch at a time, so a human can send several batches in a
    row even if the agent is briefly between polls.
    """

    def __init__(self, doc_path: str | Path, instruction: str = ""):
        self.id = "rev-" + uuid.uuid4().hex[:12]
        self.doc_path = Path(doc_path).resolve()
        self.instruction = instruction or ""
        self.created = _now()
        self.status = "waiting"  # waiting | working | done | aborted
        self._pending: deque[dict] = deque()
        self._event: asyncio.Event | None = None

    def to_public(self) -> dict:
        """JSON-safe snapshot for the browser / MCP client."""
        return {
            "session_id": self.id,
            "doc": str(self.doc_path),
            "status": self.status,
            "instruction": self.instruction,
            "created": self.created,
        }

    def _event_obj(self) -> asyncio.Event:
        # Created lazily inside the running loop so the registry can mint
        # sessions from sync code without binding to an event loop early.
        if self._event is None:
            self._event = asyncio.Event()
        return self._event

    def mark_waiting(self) -> bool:
        """Flip a working session back to waiting (agent re-polled).

        Returns True if a transition happened, so the caller can broadcast the
        new state to the browser.
        """
        if self.status == "working":
            self.status = "waiting"
            return True
        return False

    async def wait(self, timeout: float) -> dict | None:
        """Wait up to *timeout* seconds for the next browser submission.

        Returns the submission payload, or None on timeout.
        """
        if self._pending:
            return self._pending.popleft()
        ev = self._event_obj()
        ev.clear()
        try:
            await asyncio.wait_for(ev.wait(), timeout)
        except asyncio.TimeoutError:
            return None
        return self._pending.popleft() if self._pending else None

    def submit(self, comment_ids, instruction: str = "", final: bool = False) -> dict:
        """Queue a batch of comments for the waiting agent."""
        payload = {
            "action": "finish" if final else "submit",
            "comment_ids": list(comment_ids or []),
            "instruction": instruction or "",
        }
        self._pending.append(payload)
        if self._event is not None:
            self._event.set()
        self.status = "done" if final else "working"
        return payload

    def abort(self, reason: str = "cancelled") -> dict:
        """Cancel the session; the waiting agent is told the review was dropped."""
        payload = {"action": "abort", "reason": reason}
        self._pending.append(payload)
        if self._event is not None:
            self._event.set()
        self.status = "aborted"
        return payload

    def drain_pending(self) -> list[dict]:
        """Pop and return all buffered submissions still in the queue.

        Used to coalesce a burst of per-comment "Send to AI" clicks into a
        single delivery, so the agent sees them together instead of one batch
        per poll (with later ones stranded if it stops polling).
        """
        items = list(self._pending)
        self._pending.clear()
        return items

    def has_pending(self) -> bool:
        """True if a submitted batch is still buffered, awaiting collection."""
        return bool(self._pending)


class ReviewRegistry:
    """Tracks live review sessions for a server, keyed by session id."""

    def __init__(self):
        self._by_id: dict[str, ReviewSession] = {}

    def start(self, doc_path: str | Path, instruction: str = "") -> ReviewSession:
        session = ReviewSession(doc_path, instruction)
        self._by_id[session.id] = session
        return session

    def get(self, session_id: str | None) -> ReviewSession | None:
        if not session_id:
            return None
        return self._by_id.get(session_id)

    def remove(self, session_id: str) -> None:
        self._by_id.pop(session_id, None)

    def find_active(self, doc_path: str | Path) -> list[ReviewSession]:
        """Active sessions for a document, oldest first."""
        dp = Path(doc_path).resolve()
        return [
            s for s in self._by_id.values() if s.doc_path == dp and s.status in ACTIVE_STATUSES
        ]

    def find_for_rejoin(self, doc_path: str | Path) -> ReviewSession | None:
        """The session a re-issued ``request_review`` should resume, or None.

        Prefers the newest active (waiting/working) session. Falls back to a
        terminal session (done/aborted) whose batch was never delivered — so a
        "Send & finish"/"Cancel" that landed while the agent was between rounds
        is collected on the next poll instead of being stranded in an abandoned
        session while a fresh, empty one is minted. (A terminal session whose
        batch has already been drained has no pending items and is skipped.)
        """
        dp = Path(doc_path).resolve()
        mine = [s for s in self._by_id.values() if s.doc_path == dp]
        active = [s for s in mine if s.status in ACTIVE_STATUSES]
        if active:
            return active[-1]
        undelivered = [s for s in mine if s.has_pending()]
        return undelivered[-1] if undelivered else None
