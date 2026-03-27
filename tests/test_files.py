"""Tests for sidecar-aware file operations."""

from scholia.files import sidecar_paths, move_doc, remove_doc


def test_sidecar_paths_all_present(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    jsonl = tmp_path / "doc.md.scholia.jsonl"
    jsonl.write_text("{}")
    state = tmp_path / "doc.md.scholia.state.json"
    state.write_text("{}")
    paths = sidecar_paths(str(doc))
    assert jsonl in paths
    assert state in paths


def test_sidecar_paths_none_present(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    paths = sidecar_paths(str(doc))
    assert paths == []


def test_move_doc_with_sidecars(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("# Hello")
    jsonl = tmp_path / "src.md.scholia.jsonl"
    jsonl.write_text('{"id":"test"}')
    state = tmp_path / "src.md.scholia.state.json"
    state.write_text("{}")

    dest = tmp_path / "sub" / "dest.md"
    dest.parent.mkdir()

    move_doc(str(src), str(dest))

    assert not src.exists()
    assert not jsonl.exists()
    assert not state.exists()
    assert dest.exists()
    assert (tmp_path / "sub" / "dest.md.scholia.jsonl").exists()
    assert (tmp_path / "sub" / "dest.md.scholia.state.json").exists()
    assert dest.read_text() == "# Hello"


def test_move_doc_no_sidecars(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("# Hello")
    dest = tmp_path / "dest.md"
    move_doc(str(src), str(dest))
    assert not src.exists()
    assert dest.exists()


def test_move_doc_dest_exists_raises(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("a")
    dest = tmp_path / "dest.md"
    dest.write_text("b")
    import pytest

    with pytest.raises(FileExistsError):
        move_doc(str(src), str(dest))


def test_move_doc_dest_exists_force(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("a")
    dest = tmp_path / "dest.md"
    dest.write_text("b")
    move_doc(str(src), str(dest), force=True)
    assert dest.read_text() == "a"


def test_move_doc_source_missing_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        move_doc(str(tmp_path / "nope.md"), str(tmp_path / "dest.md"))


def test_remove_doc_with_sidecars(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    jsonl = tmp_path / "doc.md.scholia.jsonl"
    jsonl.write_text("{}")
    state = tmp_path / "doc.md.scholia.state.json"
    state.write_text("{}")
    removed = remove_doc(str(doc))
    assert not doc.exists()
    assert not jsonl.exists()
    assert not state.exists()
    assert len(removed) == 3


def test_remove_doc_no_sidecars(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    removed = remove_doc(str(doc))
    assert not doc.exists()
    assert len(removed) == 1


def test_remove_doc_missing_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        remove_doc(str(tmp_path / "nope.md"))
