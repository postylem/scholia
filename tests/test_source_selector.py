"""Tests for recoverable-text source selector storage and CLI resolution."""

from pathlib import Path

import pytest
import pytest_asyncio
from scholia.comments import append_comment, load_comments, reanchor
from scholia.context import locate_anchor
from scholia.server import ScholiaServer

STRESS_DOC = Path(__file__).parent / "fixtures" / "anchoring-stress.md"


@pytest.fixture
def stress_doc(tmp_path):
    """Anchoring stress-test document with math, crossrefs, footnotes."""
    src = (
        "---\ntitle: Test\n---\n\n"
        "## Identical Spans\n\n"
        "### Context Alpha\n\n"
        "The Ising model originated in statistical mechanics.\n\n"
        "Shannon's source coding theorem proves a limit.\n\n"
        "### Context Beta\n\n"
        "The Potts model generalizes the Ising model.\n\n"
        "Shannon's source coding theorem proves a limit.\n\n"
        "## Math\n\n"
        "Under mild conditions, $\\sum_k a_k$ converges $\\zeta(s)$\n"
        "to a finite limit.\n"
    )
    doc = tmp_path / "stress.md"
    doc.write_text(src)
    return doc


def test_append_comment_stores_source_selector(stress_doc):
    """Source selector stored alongside browser selector when provided."""
    ann = append_comment(
        stress_doc,
        exact="converges",
        prefix="garbled katex text ",
        suffix=" more garbled",
        body_text="test",
        source_selector={
            "exact": "converges",
            "prefix": "$\\sum_k a_k$ ",
            "suffix": " $\\zeta(s)$",
        },
    )
    target = ann["target"]
    assert target["selector"]["exact"] == "converges"
    assert target["selector"]["prefix"] == "garbled katex text "
    assert "scholia:sourceSelector" in target
    ss = target["scholia:sourceSelector"]
    assert ss["type"] == "TextQuoteSelector"
    assert ss["exact"] == "converges"
    assert ss["prefix"] == "$\\sum_k a_k$ "
    assert ss["suffix"] == " $\\zeta(s)$"


def test_append_comment_no_source_selector(stress_doc):
    """Without source_selector, no scholia:sourceSelector key stored."""
    ann = append_comment(stress_doc, exact="converges", body_text="test")
    assert "scholia:sourceSelector" not in ann["target"]


def test_source_selector_survives_load(stress_doc):
    """Source selector round-trips through JSONL storage."""
    append_comment(
        stress_doc,
        exact="converges",
        body_text="test",
        source_selector={"exact": "converges", "prefix": "p", "suffix": "s"},
    )
    loaded = load_comments(stress_doc)
    assert len(loaded) == 1
    ss = loaded[0]["target"]["scholia:sourceSelector"]
    assert ss["exact"] == "converges"


def test_reanchor_updates_source_selector(stress_doc):
    """Reanchor replaces both browser and source selectors."""
    ann = append_comment(
        stress_doc,
        exact="old text",
        body_text="test",
        source_selector={"exact": "old text", "prefix": "", "suffix": ""},
    )
    updated = reanchor(
        stress_doc,
        ann["id"],
        exact="new text",
        prefix="p",
        suffix="s",
        source_selector={"exact": "new source", "prefix": "sp", "suffix": "ss"},
    )
    assert updated["target"]["selector"]["exact"] == "new text"
    ss = updated["target"]["scholia:sourceSelector"]
    assert ss["exact"] == "new source"


def test_reanchor_clears_source_selector_when_none(stress_doc):
    """Reanchor without source_selector removes old one."""
    ann = append_comment(
        stress_doc,
        exact="text",
        body_text="test",
        source_selector={"exact": "text", "prefix": "", "suffix": ""},
    )
    updated = reanchor(stress_doc, ann["id"], exact="text")
    assert "scholia:sourceSelector" not in updated["target"]


def test_locate_anchor_uses_source_selector(stress_doc):
    """locate_anchor finds text using source selector when browser selector fails."""
    source_selector = {
        "exact": "converges",
        "prefix": "$\\sum_k a_k$ ",
        "suffix": " $\\zeta(s)$",
    }
    ctx_source = locate_anchor(stress_doc, source_selector, rendered_text=None)
    assert ctx_source["found"]
    assert "converges" in stress_doc.read_text().splitlines()[ctx_source["line"] - 1]


def test_locate_anchor_source_selector_disambiguates(stress_doc):
    """Source selector with unique prefix disambiguates identical plain text."""
    source_selector = {
        "exact": "Shannon's source coding theorem proves a limit.",
        "prefix": "The Potts model generalizes the Ising model.\n\n",
        "suffix": "\n",
    }
    ctx = locate_anchor(stress_doc, source_selector, rendered_text=None)
    assert ctx["found"]
    assert ctx["line"] == 17


def test_locate_anchor_backward_compat(tmp_path):
    """Old annotations without source selector still work."""
    doc = tmp_path / "simple.md"
    doc.write_text("---\ntitle: T\n---\n\nHello world.\n")
    selector = {"exact": "Hello world", "prefix": "", "suffix": ""}
    ctx = locate_anchor(doc, selector, rendered_text=None)
    assert ctx["found"]


# ---------------------------------------------------------------------------
# WebSocket tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ss_client(aiohttp_client, stress_doc):
    """aiohttp test client for source selector tests."""
    server = ScholiaServer(str(stress_doc))
    return await aiohttp_client(server.app), stress_doc


@pytest.mark.asyncio
async def test_ws_new_comment_with_source_selector(ss_client):
    """WebSocket new_comment passes source selector through to storage."""
    client, doc = ss_client
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(doc.resolve())})
    await ws.send_json(
        {
            "type": "new_comment",
            "exact": "converges",
            "prefix": "garbled ",
            "suffix": " garbled",
            "source_exact": "converges",
            "source_prefix": "$\\sum_k a_k$ ",
            "source_suffix": " $\\zeta(s)$",
            "body": "test comment",
        }
    )
    await ws.close()
    comments = load_comments(doc)
    assert len(comments) == 1
    ss = comments[0]["target"].get("scholia:sourceSelector")
    assert ss is not None
    assert ss["exact"] == "converges"
    assert ss["prefix"] == "$\\sum_k a_k$ "


@pytest.mark.asyncio
async def test_ws_new_comment_without_source_selector(ss_client):
    """WebSocket new_comment without source fields stores no source selector."""
    client, doc = ss_client
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(doc.resolve())})
    await ws.send_json(
        {
            "type": "new_comment",
            "exact": "converges",
            "prefix": "",
            "suffix": "",
            "body": "test",
        }
    )
    await ws.close()
    comments = load_comments(doc)
    assert "scholia:sourceSelector" not in comments[0]["target"]


@pytest.mark.asyncio
async def test_ws_reanchor_with_source_selector(ss_client):
    """WebSocket reanchor passes source selector through."""
    client, doc = ss_client
    ann = append_comment(doc, exact="converges", body_text="original")
    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(doc.resolve())})
    await ws.send_json(
        {
            "type": "reanchor",
            "annotation_id": ann["id"],
            "exact": "converges",
            "prefix": "new browser",
            "suffix": "new browser",
            "source_exact": "converges",
            "source_prefix": "new source",
            "source_suffix": "new source",
        }
    )
    await ws.close()
    comments = load_comments(doc)
    latest = comments[-1]
    assert latest["target"]["scholia:sourceSelector"]["prefix"] == "new source"


# ---------------------------------------------------------------------------
# End-to-end tests with anchoring-stress fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def stress_fixture(tmp_path):
    """Copy the anchoring stress-test fixture for isolated testing."""
    dest = tmp_path / "anchoring-stress.md"
    dest.write_text(STRESS_DOC.read_text())
    return dest


def test_math_surrounded_word_variant_one(stress_fixture):
    """Source selector disambiguates 'converges' in Variant One vs Two."""
    ann = append_comment(
        stress_fixture,
        exact="converges",
        prefix="garbled katex ",
        suffix=" garbled katex",
        body_text="Variant One comment",
        source_selector={
            "exact": "converges",
            "prefix": "$\\sum_k a_k$ ",
            "suffix": " $\\zeta(s)$\nto a finite limit when",
        },
    )
    source_sel = ann["target"]["scholia:sourceSelector"]
    ctx = locate_anchor(stress_fixture, source_sel, rendered_text=None)
    assert ctx["found"]
    line_text = stress_fixture.read_text().splitlines()[ctx["line"] - 1]
    assert "zeta(s)$" in line_text  # Variant One line, not Two


def test_math_surrounded_word_variant_two(stress_fixture):
    """Source selector disambiguates 'converges' in Variant Two."""
    ann = append_comment(
        stress_fixture,
        exact="converges",
        prefix="garbled katex ",
        suffix=" garbled katex",
        body_text="Variant Two comment",
        source_selector={
            "exact": "converges",
            "prefix": "$\\sum_k a_k$ ",
            "suffix": " $\\zeta(s)\\zeta(2s)$\nto a finite limit provided",
        },
    )
    source_sel = ann["target"]["scholia:sourceSelector"]
    ctx = locate_anchor(stress_fixture, source_sel, rendered_text=None)
    assert ctx["found"]
    line_text = stress_fixture.read_text().splitlines()[ctx["line"] - 1]
    assert "zeta(2s)" in line_text  # Variant Two line


def test_crossref_anchor(stress_fixture):
    """Source selector with @sec:id matches raw crossref in source."""
    ann = append_comment(
        stress_fixture,
        exact="sec. 1",
        prefix="As shown in ",
        suffix=", identical text",
        body_text="crossref comment",
        source_selector={
            "exact": "@sec:identical",
            "prefix": "As shown in ",
            "suffix": ", identical text",
        },
    )
    source_sel = ann["target"]["scholia:sourceSelector"]
    ctx = locate_anchor(stress_fixture, source_sel, rendered_text=None)
    assert ctx["found"]
    line_text = stress_fixture.read_text().splitlines()[ctx["line"] - 1]
    assert "@sec:identical" in line_text


def test_display_equation_anchor(stress_fixture):
    """Source selector anchors to display math with equation ID."""
    ann = append_comment(
        stress_fixture,
        exact="garbled ELBO katex",
        prefix="the objective is:\n\n",
        suffix="",
        body_text="equation comment",
        source_selector={
            "exact": (
                "$$L_\\phi = \\mathbb{E}_{z \\sim p}"
                "\\left[\\log \\frac{p(z)}{q_\\phi(z)}\\right]$$"
            ),
            "prefix": "the objective is:\n\n",
            "suffix": " {#eq:elbo}",
        },
    )
    source_sel = ann["target"]["scholia:sourceSelector"]
    ctx = locate_anchor(stress_fixture, source_sel, rendered_text=None)
    assert ctx["found"]
    line_text = stress_fixture.read_text().splitlines()[ctx["line"] - 1]
    assert "L_\\phi" in line_text or r"L_\phi" in line_text
