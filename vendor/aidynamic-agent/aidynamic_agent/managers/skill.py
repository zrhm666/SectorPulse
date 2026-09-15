from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SkillInfo:
    """Structured information about a skill."""

    name: str
    path: str  # path to SKILL.md
    dir: str  # skill directory path
    description: str
    frontmatter: dict


class SkillManager:
    """Scan skills/ directory for skill folders (each containing SKILL.md),
    parse YAML frontmatter, and provide describe/load/resource operations.

    Expected skill structure::

        skills/
        ├── my_skill/
        │   ├── SKILL.md          # main document (required)
        │   ├── references/       # reference docs (optional)
        │   ├── assets/           # config files, templates (optional)
        │   └── scripts/          # helper scripts (optional)
    """

    # Subdirectories that are recognized as resource categories
    RESOURCE_CATEGORIES = ("references", "assets", "scripts")

    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self._skills: dict[str, SkillInfo] = {}
        self._scan_skills()

    def _scan_skills(self):
        """Scan skill subdirectories for SKILL.md files."""
        if not self.skills_dir.exists():
            return
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue  # skip files like README.md
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            content = skill_md.read_text(encoding="utf-8")
            frontmatter = self._parse_frontmatter(content)
            if not frontmatter:
                continue
            name = skill_dir.name  # folder name as skill name
            self._skills[name] = SkillInfo(
                name=name,
                path=str(skill_md),
                dir=str(skill_dir),
                description=frontmatter.get("description", ""),
                frontmatter=frontmatter,
            )

    def _parse_frontmatter(self, content: str) -> dict | None:
        match = re.match(r"^---\s*\n(.+?)\n---\s*\n", content, re.DOTALL)
        if not match:
            return None
        # Simple YAML parsing (key: value lines)
        result = {}
        for line in match.group(1).split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                result[key.strip()] = value.strip().strip('"')
        return result

    def describe_available(self) -> list[dict]:
        """Return list of available skills with name and description"""
        return [
            {"name": s.name, "description": s.description, "path": str(Path(s.dir).resolve())}
            for s in self._skills.values()
        ]

    def load_full_text_with_path_hint(self, name: str) -> str | None:
        """Load SKILL.md with path hints prepended to help agent navigate.

        The hint includes:
        - Skill name and directory path
        - Instructions for using builtin file tools
        - Example commands for common operations
        """
        skill = self._skills.get(name)
        if not skill:
            return None

        skill_dir = Path(skill.dir).resolve()
        original_text = Path(skill.path).read_text(encoding="utf-8")

        hint = f"""# Skill: {name}

**Path**: {skill_dir}

You can use builtin file tools to explore this skill directory:
- Read files: `cat {skill_dir}/references/xxx.md`
- Search content: `rg "keyword" {skill_dir}/`
- Execute scripts: `python {skill_dir}/scripts/xxx.py`
- List structure: `find {skill_dir} -type f`

---

"""
        return hint + original_text
