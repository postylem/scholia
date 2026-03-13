"""Shared fixtures for scholia tests."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_doc(tmp_path):
    """Create a temporary markdown file and return its path."""
    doc = tmp_path / "test.md"
    doc.write_text("# Test\n\nSome text to anchor comments to.\n\nDuplicate text here.\n\nDuplicate text here.\n")
    return doc


@pytest.fixture
def tmp_doc_with_comments(tmp_doc):
    """Create a doc with one pre-existing comment."""
    from scholia.comments import append_comment
    append_comment(tmp_doc, exact="Some text", prefix="# Test\n\n", suffix=" to anchor", body_text="A test comment")
    return tmp_doc
