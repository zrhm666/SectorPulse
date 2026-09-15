"""Tests for agent/managers/skill.py - SkillManager."""

import pytest

from aidynamic_agent.managers.skill import SkillManager


@pytest.fixture
def skills_dir(tmp_path):
    """Create a temporary skills directory with test skill files.

    Each skill lives in its own subdirectory containing a SKILL.md
    (the documented SkillManager contract).
    """
    d = tmp_path / "skills"
    d.mkdir()
    # Skill with frontmatter
    (d / "code_review").mkdir()
    (d / "code_review" / "SKILL.md").write_text(
        "---\ndescription: Review code for issues\ncategory: coding\n---\n# Code Review\n\nReview the code..."
    )
    # Skill with frontmatter
    (d / "data_analysis").mkdir()
    (d / "data_analysis" / "SKILL.md").write_text(
        "---\ndescription: Analyze data patterns\ncategory: analysis\n---\n# Data Analysis\n\nAnalyze patterns..."
    )
    # Markdown without frontmatter
    (d / "notes").mkdir()
    (d / "notes" / "SKILL.md").write_text("# Notes\n\nJust some notes without frontmatter.")
    return d


@pytest.fixture
def empty_skills_dir(tmp_path):
    """Create an empty skills directory."""
    d = tmp_path / "empty_skills"
    d.mkdir()
    return d


class TestSkillManagerScan:
    """Test skill directory scanning."""

    def test_scan_finds_skills(self, skills_dir):
        mgr = SkillManager(skills_dir=str(skills_dir))
        # Should find 2 skills with frontmatter (code_review, data_analysis)
        assert "code_review" in mgr._skills
        assert "data_analysis" in mgr._skills
        # notes.md has no frontmatter, should not be included
        assert "notes" not in mgr._skills

    def test_scan_empty_directory(self, empty_skills_dir):
        mgr = SkillManager(skills_dir=str(empty_skills_dir))
        assert len(mgr._skills) == 0

    def test_scan_nonexistent_directory(self, tmp_path):
        mgr = SkillManager(skills_dir=str(tmp_path / "nonexistent"))
        assert len(mgr._skills) == 0


class TestSkillManagerParseFrontmatter:
    """Test YAML frontmatter parsing."""

    def test_parse_valid_frontmatter(self, skills_dir):
        mgr = SkillManager(skills_dir=str(skills_dir))
        skill = mgr._skills["code_review"]
        assert skill.frontmatter["description"] == "Review code for issues"
        assert skill.frontmatter["category"] == "coding"

    def test_parse_no_frontmatter(self, skills_dir):
        mgr = SkillManager(skills_dir=str(skills_dir))
        content = "# No frontmatter\n\nJust content."
        result = mgr._parse_frontmatter(content)
        assert result is None

    def test_parse_single_key_value(self, skills_dir):
        mgr = SkillManager(skills_dir=str(skills_dir))
        content = "---\ndescription: A simple skill\n---\n\nContent here."
        result = mgr._parse_frontmatter(content)
        assert result is not None
        assert result["description"] == "A simple skill"

    def test_parse_quoted_value(self, skills_dir):
        mgr = SkillManager(skills_dir=str(skills_dir))
        content = '---\ndescription: "Quoted description"\n---\n\nContent.'
        result = mgr._parse_frontmatter(content)
        assert result is not None
        assert result["description"] == "Quoted description"


class TestSkillManagerDescribe:
    """Test describe_available method."""

    def test_describe_returns_list(self, skills_dir):
        mgr = SkillManager(skills_dir=str(skills_dir))
        result = mgr.describe_available()
        assert isinstance(result, list)
        assert len(result) == 2

    def test_describe_contains_name_and_description(self, skills_dir):
        mgr = SkillManager(skills_dir=str(skills_dir))
        result = mgr.describe_available()
        names = {s["name"] for s in result}
        assert "code_review" in names
        assert "data_analysis" in names

    def test_describe_empty_when_no_skills(self, empty_skills_dir):
        mgr = SkillManager(skills_dir=str(empty_skills_dir))
        result = mgr.describe_available()
        assert result == []


class TestSkillManagerLoadFullText:
    """Test load_full_text_with_path_hint method."""

    def test_load_existing_skill(self, skills_dir):
        mgr = SkillManager(skills_dir=str(skills_dir))
        text = mgr.load_full_text_with_path_hint("code_review")
        assert text is not None
        assert "---" in text
        assert "Code Review" in text

    def test_load_nonexistent_skill_returns_none(self, skills_dir):
        mgr = SkillManager(skills_dir=str(skills_dir))
        text = mgr.load_full_text_with_path_hint("nonexistent_skill")
        assert text is None

    def test_load_returns_full_file_content(self, skills_dir):
        mgr = SkillManager(skills_dir=str(skills_dir))
        text = mgr.load_full_text_with_path_hint("code_review")
        # Should contain both frontmatter and body
        assert "description: Review code for issues" in text
        assert "Review the code" in text
