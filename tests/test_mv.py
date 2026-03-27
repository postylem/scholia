"""Tests for scholia mv command."""

import subprocess
import sys


def test_mv_moves_doc_and_sidecars(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("# Hello")
    jsonl = tmp_path / "src.md.scholia.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    dest = tmp_path / "dest.md"

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "mv", str(src), str(dest)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert not src.exists()
    assert dest.exists()
    assert (tmp_path / "dest.md.scholia.jsonl").exists()


def test_mv_dest_exists_errors(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("a")
    dest = tmp_path / "dest.md"
    dest.write_text("b")

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "mv", str(src), str(dest)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "already exists" in result.stderr.lower()


def test_mv_dest_exists_force(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("a")
    dest = tmp_path / "dest.md"
    dest.write_text("b")

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "mv", str(src), str(dest), "--force"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert dest.read_text() == "a"


def test_mv_source_missing_errors(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scholia.cli",
            "mv",
            str(tmp_path / "nope.md"),
            str(tmp_path / "dest.md"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
