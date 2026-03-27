"""Tests for recoverable-text source selector storage and CLI resolution."""

import pytest
from scholia.comments import append_comment, load_comments, reanchor


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
