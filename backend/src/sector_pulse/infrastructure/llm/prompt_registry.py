import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class PromptDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)
    prompt_id: str
    version: str
    system: str
    content_sha256: str


class PromptRegistry:
    """加载版本化 Prompt，并用哈希保证调用审计可复现。"""

    def __init__(self, directory: Path) -> None:
        self._definitions: dict[str, PromptDefinition] = {}
        for path in sorted(directory.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"prompt {path.name} must be a mapping")
            prompt_id = str(raw.get("prompt_id", ""))
            if not prompt_id or prompt_id in self._definitions:
                raise ValueError(f"duplicate or missing prompt id: {path.name}")
            system = str(raw.get("system", ""))
            version = str(raw.get("version", ""))
            if not system or not version:
                raise ValueError(f"prompt {path.name} requires version and system")
            normalized = f"{prompt_id}\n{version}\n{system}".encode()
            self._definitions[prompt_id] = PromptDefinition(
                prompt_id=prompt_id,
                version=version,
                system=system,
                content_sha256=hashlib.sha256(normalized).hexdigest(),
            )

    def get(self, prompt_id: str) -> PromptDefinition:
        try:
            return self._definitions[prompt_id]
        except KeyError as exc:
            raise KeyError(f"prompt is not registered: {prompt_id}") from exc
