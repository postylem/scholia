"""Tests for _server state key management."""

from scholia.state import set_server, clear_server, get_server, load_state


def test_set_server_writes_key(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    set_server(str(doc), port=8088, pid=12345)
    state = load_state(str(doc))
    assert state["_server"] == {"port": 8088, "pid": 12345}


def test_clear_server_removes_key(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    set_server(str(doc), port=8088, pid=12345)
    clear_server(str(doc))
    state = load_state(str(doc))
    assert "_server" not in state


def test_clear_server_noop_when_missing(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    clear_server(str(doc))


def test_get_server_returns_info(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    set_server(str(doc), port=8088, pid=12345)
    info = get_server(str(doc))
    assert info == {"port": 8088, "pid": 12345}


def test_get_server_returns_none_when_missing(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    assert get_server(str(doc)) is None


def test_set_server_preserves_annotation_state(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    from scholia.state import mark_read

    mark_read(str(doc), "urn:uuid:test-id")
    set_server(str(doc), port=8088, pid=1)
    state = load_state(str(doc))
    assert "urn:uuid:test-id" in state
    assert "_server" in state
