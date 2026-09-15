import hashlib
from pathlib import Path
from string import Template

import yaml
from pydantic import BaseModel, ConfigDict


class PromptDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)
    prompt_id: str
    version: str
    system: str
    content_sha256: str
    variables: tuple[str, ...] = ()

    def render(self, **values: str) -> str:
        if set(values) != set(self.variables):
            raise ValueError(f"prompt {self.prompt_id}: variables must be {self.variables}")
        return Template(self.system).substitute(values)


class PromptRegistry:
    """加载版本化 Prompt，并用哈希保证调用审计可复现。"""

    def __init__(self, directory: Path) -> None:
        self._definitions: dict[str, PromptDefinition] = {}
        if not directory.is_dir():
            raise ValueError(f"prompt directory not found: {directory}")
        for path in sorted((*directory.rglob("*.yaml"), *directory.rglob("*.yml"))):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"prompt {path.name} must be a mapping")
            for field in ("prompt_id", "version", "system"):
                if not isinstance(raw.get(field), str) or not raw[field].strip():
                    raise ValueError(f"prompt {path}: {field} must be a non-empty string")
            prompt_id = raw["prompt_id"]
            if not prompt_id or prompt_id in self._definitions:
                raise ValueError(f"duplicate or missing prompt id: {path.name}")
            system = str(raw.get("system", ""))
            version = str(raw.get("version", ""))
            if not system or not version:
                raise ValueError(f"prompt {path.name} requires version and system")
            normalized = f"{prompt_id}\n{version}\n{system}".encode()
            variables = raw.get("variables", [])
            template = Template(system)
            if (
                not isinstance(variables, list)
                or not all(isinstance(item, str) for item in variables)
                or len(variables) != len(set(variables))
                or not template.is_valid()
                or set(template.get_identifiers()) != set(variables)
            ):
                raise ValueError(f"prompt {path}: invalid or undeclared template variables")
            self._definitions[prompt_id] = PromptDefinition(
                prompt_id=prompt_id,
                version=version,
                system=system,
                content_sha256=hashlib.sha256(normalized).hexdigest(),
                variables=tuple(variables),
            )

    def get(self, prompt_id: str) -> PromptDefinition:
        try:
            return self._definitions[prompt_id]
        except KeyError as exc:
            raise KeyError(f"prompt is not registered: {prompt_id}") from exc
