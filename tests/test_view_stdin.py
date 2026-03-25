"""Tests for scholia view stdin support."""
import subprocess
import sys


def test_piped_stdin_without_dash_shows_error():
    """Piping to 'scholia view' without '-' gives helpful error."""
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "view"],
        input="# Hello",
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "did you mean" in result.stderr.lower()
