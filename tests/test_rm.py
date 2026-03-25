"""Tests for scholia rm command."""
import subprocess
import sys
from pathlib import Path


def test_rm_force_deletes_doc_and_sidecars(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    jsonl = tmp_path / "doc.md.scholia.jsonl"
    jsonl.write_text("{}")
    state = tmp_path / "doc.md.scholia.state.json"
    state.write_text("{}")

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "rm", str(doc), "--force"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert not doc.exists()
    assert not jsonl.exists()
    assert not state.exists()


def test_rm_force_no_sidecars(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "rm", str(doc), "--force"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert not doc.exists()


def test_rm_missing_file_errors(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "rm",
         str(tmp_path / "nope.md"), "--force"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


def test_rm_without_force_prompts(tmp_path):
    """Without --force, rm should prompt (and fail on non-interactive stdin)."""
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "rm", str(doc)],
        input="n\n",
        capture_output=True, text=True,
    )
    assert doc.exists()


def test_rm_without_force_confirm_yes(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "rm", str(doc)],
        input="y\n",
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert not doc.exists()
