from pathlib import Path

from aidynamic_agent.managers.skill import SkillManager


class AllowedSkillManager(SkillManager):
    """Framework SkillManager restricted to vetted in-root skill documents."""

    def __init__(self, skills_dir: str | Path, *, allowed_names: frozenset[str]) -> None:
        root = Path(skills_dir)
        if root.is_symlink():
            raise ValueError("skill root cannot be a symbolic link")
        self._resolved_root = root.resolve(strict=True)
        self._allowed_names = allowed_names
        super().__init__(skills_dir=str(root))
        self._skills = {
            name: info
            for name, info in self._skills.items()
            if name in allowed_names and self._is_safe(info.path, info.dir)
        }

    def _is_safe(self, skill_path: str, skill_dir: str) -> bool:
        directory = Path(skill_dir)
        document = Path(skill_path)
        if directory.is_symlink() or document.is_symlink():
            return False
        try:
            directory.resolve(strict=True).relative_to(self._resolved_root)
            document.resolve(strict=True).relative_to(self._resolved_root)
        except (OSError, ValueError):
            return False
        return True

    def load_full_text_with_path_hint(self, name: str) -> str | None:
        if name not in self._allowed_names or name not in self._skills:
            return None
        info = self._skills[name]
        if not self._is_safe(info.path, info.dir):
            return None
        return super().load_full_text_with_path_hint(name)


__all__ = ["AllowedSkillManager"]
