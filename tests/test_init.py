"""Tests for scholia skill-init command."""

import subprocess
import sys


def test_skill_init_default_path(tmp_path):
    """scholia skill-init writes ~/.claude/skills/scholia.md by default."""
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "skill-init"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "HOME": str(tmp_path)},
    )
    assert result.returncode == 0
    target = tmp_path / ".claude" / "skills" / "scholia" / "SKILL.md"
    assert target.exists()
    content = target.read_text()
    assert "scholia list" in content
    assert "scholia reply" in content
    assert content.startswith("---\n"), "skill file must have YAML frontmatter"
    assert "\nname: scholia\n" in content


def test_skill_init_custom_path(tmp_path):
    """scholia skill-init <path> writes to custom location."""
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "skill-init", ".cursor/rules/scholia.md"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    target = tmp_path / ".cursor" / "rules" / "scholia.md"
    assert target.exists()


def test_skill_init_skip_existing(tmp_path):
    """scholia skill-init skips if file exists."""
    target = tmp_path / ".claude" / "skills" / "scholia" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("existing content")
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "skill-init"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "HOME": str(tmp_path)},
    )
    assert result.returncode == 0
    assert "already exists" in result.stdout.lower()
    assert target.read_text() == "existing content"


def test_skill_init_force_overwrite(tmp_path):
    """scholia skill-init --force overwrites existing file."""
    target = tmp_path / ".claude" / "skills" / "scholia" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("old")
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "skill-init", "--force"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "HOME": str(tmp_path)},
    )
    assert result.returncode == 0
    assert "scholia list" in target.read_text()


def test_skill_init_template_is_agent_agnostic(tmp_path):
    """Template should not address a specific AI agent (e.g. 'you are Claude')."""
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "skill-init"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "HOME": str(tmp_path)},
    )
    assert result.returncode == 0
    target = tmp_path / ".claude" / "skills" / "scholia" / "SKILL.md"
    content = target.read_text().lower()
    # Mentioning "Claude Opus 4.6" as an example model name is fine;
    # addressing the agent as Claude ("you are Claude", "as Claude") is not.
    for phrase in ["you are claude", "as claude,", "as a claude"]:
        assert phrase not in content, f"Template should not address a specific agent: '{phrase}'"


def test_skill_template_has_render_section():
    """Skill file includes section on rendering agent responses."""
    from scholia.cli import _load_instruction_template

    content = _load_instruction_template()
    assert "Using scholia to render agent responses" in content
    # Both workflows should be present
    assert "Review Workflow" in content
    assert "scholia view" in content
