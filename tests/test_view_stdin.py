"""Tests for scholia view stdin support."""
import subprocess
import sys
import os


def test_piped_stdin_without_dash_shows_error():
    """Piping to 'scholia view' without '-' gives helpful error."""
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "view"],
        input="# Hello",
        capture_output=True, text=True,
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
