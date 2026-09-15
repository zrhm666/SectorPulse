"""Unit tests for AgentFactory."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from aidynamic_agent.agents.factory import AgentFactory
from aidynamic_agent.agents.parent import ParentAgent
from aidynamic_agent.agents.sub import SubAgent
from aidynamic_agent.core.agent import AgentConfig
from aidynamic_agent.hooks.base import HookExecutor
from aidynamic_agent.managers.skill import SkillManager
from aidynamic_agent.tools.base import Tool, ToolResult
from aidynamic_agent.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------


class DummyTool(Tool):
    """Minimal concrete tool for testing."""

    name: str = "dummy"
    description: str = "A dummy tool"
    parameters: dict = {}
    tags: list[str] = []

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(content="ok")


class DummyParentOnlyTool(DummyTool):
    name = "parent_only_tool"
    tags = ["parent_only"]

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(content="parent only")


def _make_provider():
    return MagicMock()


def _make_registry():
    reg = ToolRegistry()
    reg.register(DummyTool())
    reg.register(DummyParentOnlyTool())
    return reg


def _make_factory(provider=None, registry=None, hook_executor=None):
    return AgentFactory(
        provider=provider or _make_provider(),
        config=AgentConfig(),
        tool_registry=registry or _make_registry(),
        hook_executor=hook_executor,
    )


# ---------------------------------------------------------------------------
# AgentFactory construction tests
# ---------------------------------------------------------------------------


class TestAgentFactoryInit:
    def test_defaults(self):
        factory = AgentFactory(provider=_make_provider())
        assert factory.provider is not None
        assert isinstance(factory.config, AgentConfig)
        assert isinstance(factory.tool_registry, ToolRegistry)
        assert factory.hook_executor is None

    def test_with_all_deps(self):
        provider = _make_provider()
        registry = _make_registry()
        hook_exec = HookExecutor()
        factory = AgentFactory(
            provider=provider,
            config=AgentConfig(max_loops=5),
            tool_registry=registry,
            hook_executor=hook_exec,
        )
        assert factory.provider is provider
        assert factory.config.max_loops == 5
        assert factory.tool_registry is registry
        assert factory.hook_executor is hook_exec


# ---------------------------------------------------------------------------
# create_parent_agent tests
# ---------------------------------------------------------------------------


class TestCreateParentAgent:
    def test_returns_parent_agent(self):
        factory = _make_factory()
        agent = factory.create_parent_agent()
        assert isinstance(agent, ParentAgent)

    def test_system_prompt(self):
        factory = _make_factory()
        agent = factory.create_parent_agent(system_prompt="You are a coder")
        assert agent.config.system_prompt == "You are a coder"

    def test_config_overrides(self):
        factory = _make_factory()
        agent = factory.create_parent_agent(system_prompt="test", max_loops=5, total_timeout=60)
        assert agent.config.max_loops == 5
        assert agent.config.total_timeout == 60

    def test_uses_factory_provider_and_registry(self):
        provider = _make_provider()
        registry = _make_registry()
        factory = _make_factory(provider=provider, registry=registry)
        agent = factory.create_parent_agent()
        assert agent.provider is provider
        assert agent.tool_registry is registry

    def test_uses_factory_hook_executor(self):
        hook_exec = HookExecutor()
        factory = _make_factory(hook_executor=hook_exec)
        agent = factory.create_parent_agent()
        assert agent.hook_executor is hook_exec

    def test_unknown_overrides_ignored(self):
        """Non-AgentConfig fields should be silently ignored."""
        factory = _make_factory()
        agent = factory.create_parent_agent(unknown_field=42)
        # Should not raise; unknown_field is not a dataclass field
        assert isinstance(agent, ParentAgent)


# ---------------------------------------------------------------------------
# create_sub_agent tests
# ---------------------------------------------------------------------------


class TestCreateSubAgent:
    def test_returns_sub_agent(self):
        factory = _make_factory()
        agent = factory.create_sub_agent()
        assert isinstance(agent, SubAgent)

    def test_default_limits(self):
        factory = _make_factory()
        agent = factory.create_sub_agent()
        assert agent.config.max_loops == 10
        assert agent.config.total_timeout == 120

    def test_system_prompt(self):
        factory = _make_factory()
        agent = factory.create_sub_agent(system_prompt="research")
        assert agent.config.system_prompt == "research"

    def test_override_limits(self):
        factory = _make_factory()
        agent = factory.create_sub_agent(max_loops=20, total_timeout=300)
        assert agent.config.max_loops == 20
        assert agent.config.total_timeout == 300

    def test_sub_registry_excludes_parent_only(self):
        factory = _make_factory()
        agent = factory.create_sub_agent()
        # The sub-agent's registry should NOT contain parent_only_tool
        assert agent.tool_registry.get("dummy") is not None
        assert agent.tool_registry.get("parent_only_tool") is None

    def test_factory_provider_used(self):
        provider = _make_provider()
        factory = _make_factory(provider=provider)
        agent = factory.create_sub_agent()
        assert agent.provider is provider

    def test_factory_hook_executor_used(self):
        hook_exec = HookExecutor()
        factory = _make_factory(hook_executor=hook_exec)
        agent = factory.create_sub_agent()
        assert agent.hook_executor is hook_exec

    def test_sub_registry_is_new_instance(self):
        """Sub-agent should get its own filtered registry copy, not the original."""
        factory = _make_factory()
        agent = factory.create_sub_agent()
        assert agent.tool_registry is not factory.tool_registry


# ---------------------------------------------------------------------------
# Skill injection tests
# ---------------------------------------------------------------------------


class TestBuildSkillPrompt:
    """Test _build_skill_prompt static method."""

    def test_returns_empty_string_for_none_manager(self):
        """When skill_manager is None, should return empty string."""
        result = AgentFactory._build_skill_prompt(None)
        assert result == ""

    def test_returns_empty_string_for_empty_skills(self, tmp_path):
        """When no skills available, should return empty string."""
        empty_dir = tmp_path / "empty_skills"
        empty_dir.mkdir()
        manager = SkillManager(skills_dir=str(empty_dir))
        result = AgentFactory._build_skill_prompt(manager)
        assert result == ""

    def test_formats_single_skill(self, tmp_path):
        """Should format a single skill correctly."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "code_review" / "SKILL.md").parent.mkdir()
        (skills_dir / "code_review" / "SKILL.md").write_text(
            "---\ndescription: Review code for issues\n---\n# Code Review\n"
        )

        manager = SkillManager(skills_dir=str(skills_dir))
        result = AgentFactory._build_skill_prompt(manager)

        assert "# Available Skills" in result
        assert "**code_review**" in result
        assert "Review code for issues" in result
        assert 'skill(operation="load", name="code_review")' in result

    def test_formats_multiple_skills(self, tmp_path):
        """Should format multiple skills correctly."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        # Create first skill
        (skills_dir / "code_review" / "SKILL.md").parent.mkdir()
        (skills_dir / "code_review" / "SKILL.md").write_text(
            "---\ndescription: Review code\n---\n# Code Review\n"
        )

        # Create second skill
        (skills_dir / "data_analysis" / "SKILL.md").parent.mkdir()
        (skills_dir / "data_analysis" / "SKILL.md").write_text(
            "---\ndescription: Analyze data\n---\n# Data Analysis\n"
        )

        manager = SkillManager(skills_dir=str(skills_dir))
        result = AgentFactory._build_skill_prompt(manager)

        assert "**code_review**" in result
        assert "**data_analysis**" in result
        assert "Review code" in result
        assert "Analyze data" in result

    def test_includes_usage_instruction(self, tmp_path):
        """Should include usage instruction at the end."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "test_skill" / "SKILL.md").parent.mkdir()
        (skills_dir / "test_skill" / "SKILL.md").write_text(
            "---\ndescription: A test skill\n---\n# Test\n"
        )

        manager = SkillManager(skills_dir=str(skills_dir))
        result = AgentFactory._build_skill_prompt(manager)

        assert 'Use `skill(operation="load", name="<skill_name>")`' in result

    def test_markdown_format(self, tmp_path):
        """Should use proper Markdown formatting."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "my_skill" / "SKILL.md").parent.mkdir()
        (skills_dir / "my_skill" / "SKILL.md").write_text(
            "---\ndescription: Test description\n---\n# My Skill\n"
        )

        manager = SkillManager(skills_dir=str(skills_dir))
        result = AgentFactory._build_skill_prompt(manager)

        # Check Markdown structure
        assert result.startswith("\n# Available Skills")
        assert "- **my_skill**:" in result  # Bold name in list item


class TestSkillInjection:
    """Test skill metadata injection into system prompts."""

    def _make_skills_dir(self, tmp_path: Path) -> Path:
        """Create a temporary skills directory with test skills."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "test_skill" / "SKILL.md").parent.mkdir()
        (skills_dir / "test_skill" / "SKILL.md").write_text(
            "---\ndescription: A test skill\n---\n# Test Skill\n"
        )
        return skills_dir

    def test_inject_skill_info_default_true(self):
        """By default, inject_skill_info should be True."""
        factory = AgentFactory(provider=_make_provider())
        assert factory.inject_skill_info is True

    def test_inject_skill_info_can_be_disabled(self):
        """inject_skill_info can be set to False."""
        factory = AgentFactory(provider=_make_provider(), inject_skill_info=False)
        assert factory.inject_skill_info is False

    def test_parent_agent_injects_skill_info(self, tmp_path):
        """Parent agent should have skill info injected when enabled."""
        skills_dir = self._make_skills_dir(tmp_path)
        skill_manager = SkillManager(skills_dir=str(skills_dir))

        registry = ToolRegistry()
        registry.context.set("skill_manager", skill_manager)

        factory = AgentFactory(
            provider=_make_provider(),
            tool_registry=registry,
            inject_skill_info=True,
        )
        agent = factory.create_parent_agent(system_prompt="You are helpful.")

        assert "# Available Skills" in agent.config.system_prompt
        assert "**test_skill**" in agent.config.system_prompt
        assert "You are helpful." in agent.config.system_prompt

    def test_parent_agent_no_injection_when_disabled(self, tmp_path):
        """Parent agent should NOT have skill info when inject_skill_info=False."""
        skills_dir = self._make_skills_dir(tmp_path)
        skill_manager = SkillManager(skills_dir=str(skills_dir))

        registry = ToolRegistry()
        registry.context.set("skill_manager", skill_manager)

        factory = AgentFactory(
            provider=_make_provider(),
            tool_registry=registry,
            inject_skill_info=False,
        )
        agent = factory.create_parent_agent(system_prompt="You are helpful.")

        assert "# Available Skills" not in agent.config.system_prompt
        assert agent.config.system_prompt == "You are helpful."

    def test_parent_agent_no_injection_when_no_skill_manager(self):
        """Parent agent should NOT have skill info when no skill_manager in context."""
        registry = ToolRegistry()  # No skill_manager set

        factory = AgentFactory(
            provider=_make_provider(),
            tool_registry=registry,
            inject_skill_info=True,
        )
        agent = factory.create_parent_agent(system_prompt="You are helpful.")

        assert "# Available Skills" not in agent.config.system_prompt
        assert agent.config.system_prompt == "You are helpful."

    def test_sub_agent_no_skill_injection(self, tmp_path):
        """Sub-agent should NOT have skill info injected (per design decision)."""
        skills_dir = self._make_skills_dir(tmp_path)
        skill_manager = SkillManager(skills_dir=str(skills_dir))

        registry = ToolRegistry()
        registry.context.set("skill_manager", skill_manager)

        factory = AgentFactory(
            provider=_make_provider(),
            tool_registry=registry,
            inject_skill_info=True,
        )
        agent = factory.create_sub_agent(system_prompt="You are a sub-agent.")

        # Sub-agent should NOT have skill info injected
        assert "# Available Skills" not in agent.config.system_prompt
        assert agent.config.system_prompt == "You are a sub-agent."

    def test_skill_info_appended_to_user_prompt(self, tmp_path):
        """Skill info should be appended after user's system prompt."""
        skills_dir = self._make_skills_dir(tmp_path)
        skill_manager = SkillManager(skills_dir=str(skills_dir))

        registry = ToolRegistry()
        registry.context.set("skill_manager", skill_manager)

        factory = AgentFactory(
            provider=_make_provider(),
            tool_registry=registry,
            inject_skill_info=True,
        )
        agent = factory.create_parent_agent(system_prompt="Custom prompt.")

        # User prompt should come first
        prompt = agent.config.system_prompt
        assert prompt.startswith("Custom prompt.")
        assert "# Available Skills" in prompt
