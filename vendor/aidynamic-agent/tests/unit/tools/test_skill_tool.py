"""Unit tests for aidynamic_agent.tools.builtins.skill - SkillTool"""

from __future__ import annotations

import asyncio

import pytest

from aidynamic_agent.managers.skill import SkillManager
from aidynamic_agent.tools.builtins.skill import SkillTool
from aidynamic_agent.tools.context import ToolContext


def _run(coro):
    """Run async coroutine synchronously."""
    return asyncio.run(coro)


@pytest.fixture
def skills_dir(tmp_path):
    """Create a temporary skills directory with test skill files.

    Each skill lives in its own subdirectory containing a SKILL.md
    (the documented SkillManager contract).
    """
    d = tmp_path / "skills"
    d.mkdir()
    (d / "code_review").mkdir()
    (d / "code_review" / "SKILL.md").write_text(
        "---\ndescription: Review code for issues\ncategory: coding\n---\n# Code Review\n\nReview the code..."
    )
    (d / "data_analysis").mkdir()
    (d / "data_analysis" / "SKILL.md").write_text(
        "---\ndescription: Analyze data patterns\ncategory: analysis\n---\n# Data Analysis\n\nAnalyze patterns..."
    )
    return d


class TestSkillToolWithoutManager:
    """Test SkillTool when skill_manager is not configured."""

    def test_execute_without_manager_returns_error(self):
        tool = SkillTool()
        result = _run(tool.execute(operation="list"))
        assert result.success is False
        assert "skill_manager is not configured" in result.content
        assert result.error == "skill_manager is not configured"


class TestSkillToolList:
    """Test SkillTool list operation."""

    def test_list_with_skills(self, skills_dir):
        ctx = ToolContext()
        ctx.set("skill_manager", SkillManager(skills_dir=str(skills_dir)))
        tool = SkillTool(context=ctx)

        result = _run(tool.execute(operation="list"))
        assert result.success is True
        assert "code_review" in result.content
        assert "data_analysis" in result.content

    def test_list_no_skills(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        ctx = ToolContext()
        ctx.set("skill_manager", SkillManager(skills_dir=str(empty_dir)))
        tool = SkillTool(context=ctx)

        result = _run(tool.execute(operation="list"))
        assert result.success is True
        assert "No skills available" in result.content


class TestSkillToolLoad:
    """Test SkillTool load operation."""

    def test_load_success(self, skills_dir):
        ctx = ToolContext()
        ctx.set("skill_manager", SkillManager(skills_dir=str(skills_dir)))
        tool = SkillTool(context=ctx)

        result = _run(tool.execute(operation="load", name="code_review"))
        assert result.success is True
        assert "Code Review" in result.content
        assert "---" in result.content

    def test_load_nonexistent_skill(self, skills_dir):
        ctx = ToolContext()
        ctx.set("skill_manager", SkillManager(skills_dir=str(skills_dir)))
        tool = SkillTool(context=ctx)

        result = _run(tool.execute(operation="load", name="nonexistent"))
        assert result.success is False
        assert "not found" in result.content

    def test_load_without_name(self, skills_dir):
        ctx = ToolContext()
        ctx.set("skill_manager", SkillManager(skills_dir=str(skills_dir)))
        tool = SkillTool(context=ctx)

        result = _run(tool.execute(operation="load"))
        assert result.success is False
        assert "name is required" in result.content


class TestSkillToolUnknownOperation:
    """Test SkillTool with unknown operation."""

    def test_unknown_operation_returns_error(self, skills_dir):
        ctx = ToolContext()
        ctx.set("skill_manager", SkillManager(skills_dir=str(skills_dir)))
        tool = SkillTool(context=ctx)

        result = _run(tool.execute(operation="delete"))
        assert result.success is False
        assert "unknown operation" in result.content


class TestSkillToolDefinition:
    """Test SkillTool metadata."""

    def test_name(self):
        assert SkillTool.name == "skill"

    def test_description(self):
        assert "list available skills" in SkillTool.description

    def test_tags(self):
        assert "skill" in SkillTool.tags

    def test_to_tool_definition(self):
        tool = SkillTool()
        definition = tool.to_tool_definition()
        assert definition.name == "skill"
        assert "operation" in definition.input_schema["properties"]


class TestSkillToolRun:
    """Test SkillTool via the run template method."""

    def test_run_adds_metadata(self, skills_dir):
        ctx = ToolContext()
        ctx.set("skill_manager", SkillManager(skills_dir=str(skills_dir)))
        tool = SkillTool(context=ctx)

        result = _run(tool.run(operation="list"))
        assert result.success is True
        assert "execution_time" in result.metadata
        assert result.metadata["tool_name"] == "skill"
