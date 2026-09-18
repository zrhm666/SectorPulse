import hashlib
import json
from pathlib import Path
from string import Template

import yaml
from pydantic import BaseModel, ConfigDict

from sector_pulse.domain.llm import PromptExample, PromptTurn


class PromptDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)
    prompt_id: str
    version: str
    system: str
    content_sha256: str
    variables: tuple[str, ...] = ()
    examples: tuple[PromptExample, ...] = ()
    demonstrations: tuple[PromptTurn, ...] = ()

    def render(self, **values: str) -> str:
        if set(values) != set(self.variables):
            raise ValueError(f"prompt {self.prompt_id}: variables must be {self.variables}")
        return Template(self.system).substitute(values)


def _parse_demonstrations(path: Path, raw: object) -> tuple[PromptTurn, ...]:
    """校验示范对话，保证工具调用与工具结果成对且顺序合法。"""
    if not isinstance(raw, list):
        raise ValueError(f"prompt {path}: demonstrations must be a list")
    turns: list[PromptTurn] = []
    pending: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"prompt {path}: demonstration {index} must be a mapping")
        role = item.get("role")
        if role not in {"user", "assistant", "tool"}:
            raise ValueError(f"prompt {path}: demonstration {index} has invalid role {role!r}")
        text = item.get("text", "")
        tool_call_id = item.get("tool_call_id", "")
        tool_name = item.get("tool_name", "")
        tool_arguments = item.get("tool_arguments", {})
        if not isinstance(text, str):
            raise ValueError(f"prompt {path}: demonstration {index} text must be a string")
        if not isinstance(tool_call_id, str) or not isinstance(tool_name, str):
            raise ValueError(f"prompt {path}: demonstration {index} tool ids must be strings")
        if not isinstance(tool_arguments, dict):
            raise ValueError(f"prompt {path}: demonstration {index} arguments must be a mapping")
        if role == "tool":
            if not tool_call_id or not text.strip() or tool_name:
                raise ValueError(
                    f"prompt {path}: demonstration {index} tool result needs "
                    "tool_call_id and text only"
                )
            if tool_call_id not in pending:
                raise ValueError(
                    f"prompt {path}: demonstration {index} answers unknown tool_call_id "
                    f"{tool_call_id!r}"
                )
            pending.discard(tool_call_id)
        elif role == "user":
            if not text.strip() or tool_call_id or tool_name or tool_arguments:
                raise ValueError(f"prompt {path}: demonstration {index} user turn needs text only")
        else:
            if not text.strip() and not tool_name:
                raise ValueError(
                    f"prompt {path}: demonstration {index} assistant turn needs text or a tool call"
                )
            if tool_name:
                if not tool_call_id or tool_call_id in pending:
                    raise ValueError(
                        f"prompt {path}: demonstration {index} needs a fresh tool_call_id"
                    )
                pending.add(tool_call_id)
            elif tool_call_id or tool_arguments:
                raise ValueError(
                    f"prompt {path}: demonstration {index} has tool fields without tool_name"
                )
        turns.append(
            PromptTurn(
                role=role,
                text=text,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_arguments=tool_arguments,
            )
        )
    if pending:
        raise ValueError(f"prompt {path}: unanswered tool calls {sorted(pending)}")
    return tuple(turns)


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
            raw_examples = raw.get("examples", [])
            if not isinstance(raw_examples, list) or not all(
                isinstance(item, dict)
                and isinstance(item.get("input"), str)
                and item["input"].strip()
                and isinstance(item.get("output"), str)
                and item["output"].strip()
                for item in raw_examples
            ):
                raise ValueError(f"prompt {path}: each example requires non-empty input and output")
            examples = tuple(
                PromptExample(input=item["input"], output=item["output"]) for item in raw_examples
            )
            demonstrations = _parse_demonstrations(path, raw.get("demonstrations", []))
            # 无示例的模板保持原哈希，既有审计记录可以继续按版本比对。
            normalized = f"{prompt_id}\n{version}\n{system}"
            if examples:
                normalized += "\n" + json.dumps(
                    [example.model_dump() for example in examples],
                    ensure_ascii=False,
                    sort_keys=True,
                )
            if demonstrations:
                normalized += "\n" + json.dumps(
                    [turn.model_dump() for turn in demonstrations],
                    ensure_ascii=False,
                    sort_keys=True,
                )
            self._definitions[prompt_id] = PromptDefinition(
                prompt_id=prompt_id,
                version=version,
                system=system,
                content_sha256=hashlib.sha256(normalized.encode()).hexdigest(),
                variables=tuple(variables),
                examples=examples,
                demonstrations=demonstrations,
            )

    def get(self, prompt_id: str) -> PromptDefinition:
        try:
            return self._definitions[prompt_id]
        except KeyError as exc:
            raise KeyError(f"prompt is not registered: {prompt_id}") from exc
