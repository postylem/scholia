"""Read/write .scholia.jsonl comment store (W3C Web Annotation format)."""

import getpass
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def get_human_username() -> str:
    """Return the human user's display name for annotations.

    Checks SCHOLIA_USERNAME env var first, falls back to system username.
    AI agents should pass --author-ai-model to identify themselves rather than relying on this.
    """
    return os.environ.get("SCHOLIA_USERNAME") or getpass.getuser()


def annotation_path(doc_path: str | Path) -> Path:
    """Return .scholia.jsonl path for a given document."""
    p = Path(doc_path).resolve()
    return p.parent / f"{p.name}.scholia.jsonl"


def resolve_id(doc_path: str | Path, prefix: str) -> str:
    """Resolve a (possibly abbreviated) annotation ID to its full form.

    Accepts a full ID, a prefix of one, or just the UUID portion without
    the urn:uuid: prefix. Raises ValueError if no match or ambiguous.
    """
    comments = load_comments(doc_path)
    # Exact match first
    for c in comments:
        if c["id"] == prefix:
            return c["id"]
    # Prefix match
    matches = [c["id"] for c in comments if c["id"].startswith(prefix)]
    # Also try matching without the urn:uuid: prefix
    if not matches:
        matches = [
            c["id"] for c in comments if c["id"].removeprefix("urn:uuid:").startswith(prefix)
        ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous ID prefix '{prefix}' matches {len(matches)} annotations: "
            + ", ".join(matches[:3])
            + ("..." if len(matches) > 3 else "")
        )
    raise ValueError(f"Annotation {prefix} not found")


def short_id_map(doc_path: str | Path) -> dict[str, str]:
    """Map full annotation IDs to minimum unique prefixes (floor 4 chars).

    Strips the urn:uuid: prefix before computing uniqueness.
    Computes against ALL annotations in the file for stable results
    regardless of display filters. Returns {} for empty annotation files.
    """
    comments = load_comments(doc_path)
    if not comments:
        return {}
    full_ids = [c["id"] for c in comments]
    uuid_parts = [fid.removeprefix("urn:uuid:") for fid in full_ids]

    # Find minimum prefix length where all UUIDs are unique
    min_len = 4
    while min_len < max(len(u) for u in uuid_parts):
        prefixes = [u[:min_len] for u in uuid_parts]
        if len(set(prefixes)) == len(prefixes):
            break
        min_len += 1

    return {fid: uuid[:min_len] for fid, uuid in zip(full_ids, uuid_parts)}


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
            print(
                f"warning: skipping corrupt line {i} in {path.name}: {e}",
                file=sys.stderr,
            )
    return list(annotations.values())


def _make_creator(
    name: str,
    nickname: str | None = None,
    is_software: bool = False,
) -> dict:
    """Build a W3C Web Annotation creator object."""
    obj = {
        "type": "Software" if is_software else "Person",
        "name": name,
    }
    if nickname:
        obj["nickname"] = nickname
    return obj


def _pandoc_plain(text: str) -> str:
    """Convert markdown to plain text via Pandoc. Returns original on failure."""
    import shutil
    import subprocess

    if not shutil.which("pandoc"):
        return text
    try:
        result = subprocess.run(
            ["pandoc", "-f", "markdown", "-t", "plain", "--wrap=none"],
            input=text,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.rstrip("\n")
    except (subprocess.TimeoutExpired, OSError):
        pass
    return text


def append_comment(
    doc_path: str | Path,
    exact: str,
    prefix: str = "",
    suffix: str = "",
    body_text: str = "",
    creator: str | None = None,
    nickname: str | None = None,
    is_software: bool = False,
) -> dict:
    """Create a new annotation with a TextQuoteSelector."""
    if creator is None:
        creator = get_human_username()
    # AI agents read raw markdown; the browser anchors against rendered text.
    # Strip markdown formatting so AI anchors match the rendered document.
    if is_software:
        exact = _pandoc_plain(exact)
    now = datetime.now(timezone.utc).isoformat()
    creator_obj = _make_creator(creator, nickname, is_software=is_software)
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
    creator: str | None = None,
    nickname: str | None = None,
    is_software: bool = False,
) -> dict:
    """Append a reply to an existing annotation thread."""
    if creator is None:
        creator = get_human_username()
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
            "creator": _make_creator(creator, nickname, is_software=is_software),
            "created": now,
        }
    )
    ann["modified"] = now

    path = annotation_path(doc_path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ann) + "\n")
    return ann


def edit_body(
    doc_path: str | Path,
    annotation_id: str,
    new_text: str,
) -> dict:
    """Edit the last body entry of an annotation."""
    comments = load_comments(doc_path)
    ann = None
    for c in comments:
        if c["id"] == annotation_id:
            ann = c
            break
    if ann is None:
        raise ValueError(f"Annotation {annotation_id} not found")

    if not ann.get("body"):
        raise ValueError(f"Annotation {annotation_id} has no body entries")

    now = datetime.now(timezone.utc).isoformat()
    ann["body"][-1]["value"] = new_text
    ann["body"][-1]["modified"] = now
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


def reanchor(
    doc_path: str | Path,
    annotation_id: str,
    exact: str,
    prefix: str = "",
    suffix: str = "",
) -> dict:
    """Re-anchor an annotation to new text."""
    comments = load_comments(doc_path)
    ann = None
    for c in comments:
        if c["id"] == annotation_id:
            ann = c
            break
    if ann is None:
        raise ValueError(f"Annotation {annotation_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    ann["target"]["selector"] = {
        "type": "TextQuoteSelector",
        "exact": exact,
        "prefix": prefix,
        "suffix": suffix,
    }
    ann["modified"] = now

    path = annotation_path(doc_path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ann) + "\n")
    return ann
