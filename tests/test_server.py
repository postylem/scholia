"""Integration tests for the scholia server."""

import json
import re
from pathlib import Path

import pytest
import pytest_asyncio

from scholia.comments import append_comment, load_comments
from scholia.server import ScholiaServer
from scholia.state import load_state


@pytest.fixture
def server_app(tmp_doc):
    """Create a ScholiaServer app for testing."""
    server = ScholiaServer(str(tmp_doc))
    return server


@pytest_asyncio.fixture
async def client(aiohttp_client, server_app):
    return await aiohttp_client(server_app.app)


@pytest.mark.asyncio
async def test_index_returns_html(client):
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "scholia-container" in text
    assert "__SCHOLIA_COMMENTS__" in text
    assert "__SCHOLIA_STATE__" in text


@pytest.mark.asyncio
async def test_index_uses_yaml_title(client):
    """Page <title> should come from YAML frontmatter."""
    resp = await client.get("/")
    text = await resp.text()
    assert "<title>Test Document</title>" in text


@pytest.mark.asyncio
async def test_static_files(client):
    resp = await client.get("/static/scholia.js")
    assert resp.status == 200


@pytest.mark.asyncio
async def test_ws_new_comment(client, tmp_doc):
    ws = await client.ws_connect("/ws")
    await ws.send_json({
        "type": "new_comment",
        "exact": "Some text",
        "prefix": "",
        "suffix": "",
        "body": "test comment",
    })
    await ws.close()
    comments = load_comments(tmp_doc)
    assert len(comments) == 1
    assert comments[0]["body"][0]["value"] == "test comment"


@pytest.mark.asyncio
async def test_ws_reply(client, tmp_doc):
    ann = append_comment(tmp_doc, exact="Some text", body_text="hi")
    ws = await client.ws_connect("/ws")
    await ws.send_json({
        "type": "reply",
        "annotation_id": ann["id"],
        "body": "reply text",
        "creator": "human",
    })
    await ws.close()
    comments = load_comments(tmp_doc)
    assert len(comments[0]["body"]) == 2


@pytest.mark.asyncio
async def test_ws_resolve(client, tmp_doc):
    ann = append_comment(tmp_doc, exact="Some text", body_text="hi")
    ws = await client.ws_connect("/ws")
    await ws.send_json({
        "type": "resolve",
        "annotation_id": ann["id"],
    })
    await ws.close()
    comments = load_comments(tmp_doc)
    assert comments[0]["scholia:status"] == "resolved"
    # Resolve should also mark as read
    state = load_state(tmp_doc)
    assert ann["id"] in state
    assert state[ann["id"]]["lastReadAt"] is not None


@pytest.mark.asyncio
async def test_ws_edit_body(client, tmp_doc):
    ann = append_comment(tmp_doc, exact="Some text", body_text="original")
    ws = await client.ws_connect("/ws")
    await ws.send_json({
        "type": "edit_body",
        "annotation_id": ann["id"],
        "body": "edited text",
    })
    await ws.close()
    comments = load_comments(tmp_doc)
    assert comments[0]["body"][-1]["value"] == "edited text"


@pytest.mark.asyncio
async def test_ws_mark_read(client, tmp_doc):
    ann = append_comment(tmp_doc, exact="Some text", body_text="hi")
    ws = await client.ws_connect("/ws")
    await ws.send_json({
        "type": "mark_read",
        "annotation_id": ann["id"],
    })
    await ws.close()
    state = load_state(tmp_doc)
    assert ann["id"] in state
    assert state[ann["id"]]["lastReadAt"] is not None


@pytest.mark.asyncio
async def test_ws_mark_unread(client, tmp_doc):
    ann = append_comment(tmp_doc, exact="Some text", body_text="hi")
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "mark_read", "annotation_id": ann["id"]})
    await ws.send_json({"type": "mark_unread", "annotation_id": ann["id"]})
    await ws.close()
    state = load_state(tmp_doc)
    assert state[ann["id"]]["lastReadAt"] is None


# ── Static analysis ──────────────────────────────────


def test_form_elements_have_name_or_id():
    """Every dynamically created textarea/input must have a name or id.

    Chrome DevTools flags form fields without these attributes, and the
    warnings accumulate across re-renders, making it look like a leak.
    """
    js_path = Path(__file__).resolve().parent.parent / "scholia" / "static" / "scholia.js"
    source = js_path.read_text()
    lines = source.splitlines()

    # Find all createElement('textarea') and createElement('input') calls
    pattern = re.compile(r"""createElement\(['"](textarea|input)['"]\)""")
    violations = []
    window = 8  # lines to look ahead for .name or .id assignment

    for i, line in enumerate(lines):
        if pattern.search(line):
            # Extract the variable name (e.g. "var replyTextarea = ...")
            var_match = re.search(r"var\s+(\w+)\s*=", line)
            if not var_match:
                continue
            var_name = var_match.group(1)

            # Check next `window` lines for .name or .id assignment
            snippet = "\n".join(lines[i : i + window])
            has_name = re.search(rf"{var_name}\.name\s*=", snippet)
            has_id = re.search(rf"{var_name}\.id\s*=", snippet)

            if not has_name and not has_id:
                violations.append(f"line {i + 1}: {line.strip()}")

    assert violations == [], (
        "Form elements created without name or id attribute:\n"
        + "\n".join(violations)
    )
