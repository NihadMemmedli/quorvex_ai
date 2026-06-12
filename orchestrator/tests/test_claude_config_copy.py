from pathlib import Path

from orchestrator.utils.claude_config import copy_claude_project_config


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_copy_claude_project_config_excludes_local_settings_and_memory(tmp_path):
    source = tmp_path / "project" / ".claude"
    destination = tmp_path / "run" / ".claude"

    _write(source / "agents" / "playwright-test-planner.md", "agent")
    _write(source / "prompts" / "playwright-test-plan.md", "prompt")
    _write(source / "skills" / "playwright" / "SKILL.md", "skill")
    _write(source / "settings.local.json", '{"permissions": {}}')
    _write(source / "settings.json", '{"project": true}')
    _write(source / "memory" / "notes.md", "private memory")

    assert copy_claude_project_config(source, destination)

    assert (destination / "agents" / "playwright-test-planner.md").read_text() == "agent"
    assert (destination / "prompts" / "playwright-test-plan.md").read_text() == "prompt"
    assert (destination / "skills" / "playwright" / "SKILL.md").read_text() == "skill"
    assert not (destination / "settings.local.json").exists()
    assert not (destination / "settings.json").exists()
    assert not (destination / "memory").exists()


def test_copy_claude_project_config_removes_stale_local_settings(tmp_path):
    source = tmp_path / "project" / ".claude"
    destination = tmp_path / "run" / ".claude"

    _write(source / "agents" / "test-agent.md", "agent")
    _write(destination / "settings.local.json", "stale")
    _write(destination / "settings.json", "stale")
    _write(destination / "memory" / "notes.md", "stale")

    assert copy_claude_project_config(source, destination)

    assert (destination / "agents" / "test-agent.md").read_text() == "agent"
    assert not (destination / "settings.local.json").exists()
    assert not (destination / "settings.json").exists()
    assert not (destination / "memory").exists()
