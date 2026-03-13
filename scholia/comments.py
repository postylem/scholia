"""Read/write .scholia.jsonl comment store (W3C Web Annotation format)."""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def annotation_path(doc_path: str | Path) -> Path:
    """Return .scholia.jsonl path for a given document."""
    p = Path(doc_path).resolve()
    return p.parent / f"{p.name}.scholia.jsonl"


def load_comments(doc_path: str | Path) -> list[dict]:
    """Load all annotations, deduplicated by id (last version wins)."""
    path = annotation_path(doc_path)
    if not path.exists():
        return []
    annotations: dict[str, dict] = {}
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            ann = json.loads(line)
            annotations[ann["id"]] = ann
        except (json.JSONDecodeError, KeyError) as e:
            print(f"warning: skipping corrupt line {i} in {path.name}: {e}", file=sys.stderr)
    return list(annotations.values())


def append_comment(
    doc_path: str | Path,
    exact: str,
    prefix: str = "",
    suffix: str = "",
    body_text: str = "",
    creator: str = "human",
) -> dict:
    """Create a new annotation with a TextQuoteSelector."""
    now = datetime.now(timezone.utc).isoformat()
    creator_obj = {
        "type": "Person" if creator == "human" else "Software",
        "name": creator,
    }
    ann = {
        "@context": "http://www.w3.org/ns/anno.jsonld",
        "id": f"urn:uuid:{uuid.uuid4()}",
        "type": "Annotation",
        "created": now,
        "creator": creator_obj,
        "target": {
            "selector": {
                "type": "TextQuoteSelector",
                "exact": exact,
                "prefix": prefix,
                "suffix": suffix,
            }
        },
        "body": [
            {
                "type": "TextualBody",
                "value": body_text,
                "creator": creator_obj,
                "created": now,
            }
        ],
        "scholia:status": "open",
    }
    path = annotation_path(doc_path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ann) + "\n")
    return ann


def append_reply(
    doc_path: str | Path,
    annotation_id: str,
    body_text: str,
    creator: str = "ai",
) -> dict:
    """Append a reply to an existing annotation thread."""
    comments = load_comments(doc_path)
    ann = None
    for c in comments:
        if c["id"] == annotation_id:
            ann = c
            break
    if ann is None:
        raise ValueError(f"Annotation {annotation_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    ann["body"].append(
        {
            "type": "TextualBody",
            "value": body_text,
            "creator": {
                "type": "Person" if creator == "human" else "Software",
                "name": creator,
            },
            "created": now,
        }
    )
    ann["modified"] = now

    path = annotation_path(doc_path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ann) + "\n")
    return ann


def list_open(doc_path: str | Path) -> list[dict]:
    """List annotations with open status."""
    return [c for c in load_comments(doc_path) if c.get("scholia:status") == "open"]


def resolve(doc_path: str | Path, annotation_id: str) -> dict:
    """Mark an annotation as resolved."""
    comments = load_comments(doc_path)
    ann = None
    for c in comments:
        if c["id"] == annotation_id:
            ann = c
            break
    if ann is None:
        raise ValueError(f"Annotation {annotation_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    ann["scholia:status"] = "resolved"
    ann["scholia:resolvedAt"] = now
    ann["modified"] = now

    path = annotation_path(doc_path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ann) + "\n")
    return ann


def unresolve(doc_path: str | Path, annotation_id: str) -> dict:
    """Mark an annotation as open again."""
    comments = load_comments(doc_path)
    ann = None
    for c in comments:
        if c["id"] == annotation_id:
            ann = c
            break
    if ann is None:
        raise ValueError(f"Annotation {annotation_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    ann["scholia:status"] = "open"
    ann.pop("scholia:resolvedAt", None)
    ann["modified"] = now

    path = annotation_path(doc_path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ann) + "\n")
    return ann
