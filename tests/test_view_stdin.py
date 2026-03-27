"""Tests for scholia view stdin support."""

import subprocess
import sys
import os


def test_piped_stdin_without_dash_shows_error():
    """Piping to 'scholia view' without '-' gives helpful error."""
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "view"],
        input="# Hello",
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "did you mean" in result.stderr.lower()


def test_stdin_to_tempfile_creates_file():
    """_stdin_to_tempfile writes stdin content to a temp .md file."""
    from scholia.cli import _stdin_to_tempfile

    path = _stdin_to_tempfile("# Hello world\n")
    try:
        assert os.path.exists(path)
        assert path.endswith(".md")
        assert "scholia-" in os.path.basename(path)
        content = open(path).read()
        assert content == "# Hello world\n"
    finally:
        os.unlink(path)


def test_stdin_to_tempfile_non_utf8_errors():
    """_stdin_to_tempfile raises ValueError on non-UTF-8 input."""
    from scholia.cli import _stdin_to_tempfile
    import pytest

    with pytest.raises(ValueError, match="not valid UTF-8"):
        _stdin_to_tempfile(b"\x80\x81\x82")


def test_stdin_to_tempfile_with_title():
    """_stdin_to_tempfile prepends YAML frontmatter when title given."""
    from scholia.cli import _stdin_to_tempfile

    path = _stdin_to_tempfile("Body text\n", title="My Title")
    try:
        content = open(path).read()
        assert content.startswith("---\ntitle: My Title\n---\n\n")
        assert content.endswith("Body text\n")
    finally:
        os.unlink(path)


def test_stdin_to_tempfile_empty_content():
    """Empty stdin creates a file (possibly with just frontmatter)."""
    from scholia.cli import _stdin_to_tempfile

    path = _stdin_to_tempfile("", title="Empty")
    try:
        content = open(path).read()
        assert "title: Empty" in content
        assert os.path.exists(path)
    finally:
        os.unlink(path)


def test_stdin_to_tempfile_empty_no_title():
    """Empty stdin with no title creates an empty file."""
    from scholia.cli import _stdin_to_tempfile

    path = _stdin_to_tempfile("")
    try:
        assert os.path.exists(path)
        assert open(path).read() == ""
    finally:
        os.unlink(path)


def test_title_flag_with_file_shows_warning(tmp_path):
    """--title with a file path prints a warning to stderr."""
    doc = tmp_path / "test.md"
    doc.write_text("# Hello")
    # Start the server; it won't exit on its own, so use a short timeout.
    # subprocess.run raises TimeoutExpired — check stderr on the exception.
    try:
        subprocess.run(
            [sys.executable, "-m", "scholia.cli", "view", str(doc), "--title", "Foo"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except subprocess.TimeoutExpired as e:
        assert e.stderr is not None
        assert "warning" in e.stderr.decode().lower()
