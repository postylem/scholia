"""Read/unread state management via <doc>.scholia.state.json sidecar."""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def state_path(doc_path: str | Path) -> Path:
    """Return .scholia.state.json path for a given document."""
    p = Path(doc_path).resolve()
    return p.parent / f"{p.name}.scholia.state.json"


def load_state(doc_path: str | Path) -> dict:
    """Load state dict. Returns {} if file missing or corrupt."""
    sp = state_path(doc_path)
    if not sp.exists():
        return {}
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as e:
        print(f"warning: corrupt state file {sp.name}: {e}", file=sys.stderr)
        return {}


def _write_state(doc_path: str | Path, state: dict):
    """Atomic write: tempfile + os.replace."""
    sp = state_path(doc_path)
    data = json.dumps(state, indent=2)
    fd, tmp = tempfile.mkstemp(dir=sp.parent, suffix=".tmp")
    try:
        os.write(fd, data.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, sp)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def mark_read(doc_path: str | Path, annotation_id: str):
    """Set lastReadAt to now (UTC)."""
    state = load_state(doc_path)
    state[annotation_id] = {
        "lastReadAt": datetime.now(timezone.utc).isoformat(),
    }
    _write_state(doc_path, state)


def mark_unread(doc_path: str | Path, annotation_id: str):
    """Clear lastReadAt."""
    state = load_state(doc_path)
    state[annotation_id] = {"lastReadAt": None}
    _write_state(doc_path, state)


def is_unread(annotation: dict, ann_state: dict | None) -> bool:
    """Check if an annotation has messages newer than lastReadAt."""
    if ann_state is None or ann_state.get("lastReadAt") is None:
        return True
    last_read = datetime.fromisoformat(ann_state["lastReadAt"])
    for msg in annotation.get("body", []):
        msg_time = datetime.fromisoformat(msg["created"])
        if msg_time > last_read:
            return True
    return False


def set_server(doc_path: str | Path, port: int, pid: int):
    """Record that a scholia view server is running for this document."""
    state = load_state(doc_path)
    state["_server"] = {"port": port, "pid": pid}
    _write_state(doc_path, state)


def clear_server(doc_path: str | Path):
    """Remove server presence record."""
    state = load_state(doc_path)
    state.pop("_server", None)
    _write_state(doc_path, state)


def get_server(doc_path: str | Path) -> dict | None:
    """Return server info dict or None if no server is running."""
    state = load_state(doc_path)
    return state.get("_server")
