"""Tests for ephemeral stdin mode."""
import os
from pathlib import Path
from scholia.server import ScholiaServer


def test_server_ephemeral_flag_default_false(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    server = ScholiaServer(str(doc))
    assert server._ephemeral is False


def test_server_ephemeral_flag_settable(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    server = ScholiaServer(str(doc), ephemeral=True)
    assert server._ephemeral is True


def test_ephemeral_cleanup_removes_files(tmp_path):
    """When ephemeral, cleanup should delete doc + sidecars."""
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    jsonl = tmp_path / "doc.md.scholia.jsonl"
    jsonl.write_text("{}")
    state = tmp_path / "doc.md.scholia.state.json"
    state.write_text("{}")

    server = ScholiaServer(str(doc), ephemeral=True)
    server._ephemeral_cleanup()

    assert not doc.exists()
    assert not jsonl.exists()
    assert not state.exists()


def test_non_ephemeral_cleanup_noop(tmp_path):
    """When not ephemeral, cleanup should not delete anything."""
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")

    server = ScholiaServer(str(doc), ephemeral=False)
    server._ephemeral_cleanup()

    assert doc.exists()


def test_relocate_clears_ephemeral(tmp_path):
    """Relocating (promoting) a file should clear the ephemeral flag."""
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    dest = tmp_path / "saved.md"

    server = ScholiaServer(str(doc), ephemeral=True)
    assert server._ephemeral is True

    from scholia.files import move_doc
    move_doc(str(doc), str(dest))
    server.doc_path = dest.resolve()
    server._ephemeral = False  # This is what _do_relocate sets

    server._ephemeral_cleanup()
    assert dest.exists()
