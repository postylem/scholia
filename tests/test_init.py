"""Tests for scholia skill-init command."""
import subprocess
import sys


def test_skill_init_default_path(tmp_path):
    """scholia skill-init writes ~/.claude/skills/scholia.md by default."""
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "skill-init"],
        cwd=str(tmp_path),
        capture_output=True, text=True,
        env={**__import__("os").environ, "HOME": str(tmp_path)},
    )
    assert result.returncode == 0
    target = tmp_path / ".claude" / "skills" / "scholia.md"
    assert target.exists()
    content = target.read_text()
    assert "scholia list" in content
    assert "scholia reply" in content


def test_skill_init_custom_path(tmp_path):
    """scholia skill-init <path> writes to custom location."""
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "skill-init", ".cursor/rules/scholia.md"],
        cwd=str(tmp_path),
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    target = tmp_path / ".cursor" / "rules" / "scholia.md"
    assert target.exists()


def test_skill_init_skip_existing(tmp_path):
    """scholia skill-init skips if file exists."""
    target = tmp_path / ".claude" / "skills" / "scholia.md"
    target.parent.mkdir(parents=True)
    target.write_text("existing content")
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "skill-init"],
        cwd=str(tmp_path),
        capture_output=True, text=True,
        env={**__import__("os").environ, "HOME": str(tmp_path)},
    )
    assert result.returncode == 0
    assert "already exists" in result.stdout.lower()
    assert target.read_text() == "existing content"


def test_skill_init_force_overwrite(tmp_path):
    """scholia skill-init --force overwrites existing file."""
    target = tmp_path / ".claude" / "skills" / "scholia.md"
    target.parent.mkdir(parents=True)
    target.write_text("old")
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "skill-init", "--force"],
        cwd=str(tmp_path),
        capture_output=True, text=True,
        env={**__import__("os").environ, "HOME": str(tmp_path)},
    )
    assert result.returncode == 0
    assert "scholia list" in target.read_text()


def test_skill_init_template_is_agent_agnostic(tmp_path):
    """Template should not contain Claude-specific language."""
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "skill-init"],
        cwd=str(tmp_path),
        capture_output=True, text=True,
        env={**__import__("os").environ, "HOME": str(tmp_path)},
    )
    assert result.returncode == 0
    target = tmp_path / ".claude" / "skills" / "scholia.md"
    content = target.read_text().lower()
    assert "claude" not in content
