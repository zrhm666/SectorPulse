from pathlib import Path

import pytest
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry


def test_prompt_hash_is_stable(tmp_path: Path) -> None:
    (tmp_path / "attribution.yaml").write_text(
        "prompt_id: attribution\nversion: '1.0.0'\nsystem: test\n", encoding="utf-8"
    )
    registry = PromptRegistry(tmp_path)
    first = registry.get("attribution")
    second = registry.get("attribution")
    assert first.content_sha256 == second.content_sha256


def test_nested_template_renders_json_without_interpreting_inserted_values(tmp_path):
    module = tmp_path / "infrastructure" / "llm"
    module.mkdir(parents=True)
    (module / "output.yaml").write_text(
        "prompt_id: output\nversion: '1'\nvariables: [schema]\nsystem: 'Schema: ${schema}'\n",
        encoding="utf-8",
    )
    prompt = PromptRegistry(tmp_path).get("output")
    assert prompt.render(schema='{"value": "${secret}"}') == 'Schema: {"value": "${secret}"}'
    with pytest.raises(ValueError):
        prompt.render()
    with pytest.raises(ValueError):
        prompt.render(schema="{}", extra="unexpected")


def test_duplicate_ids_across_modules_are_rejected(tmp_path):
    for name in ("a", "b"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "prompt.yaml").write_text(
            "prompt_id: duplicate\nversion: '1'\nsystem: test\n", encoding="utf-8"
        )
    with pytest.raises(ValueError, match="duplicate"):
        PromptRegistry(tmp_path)


@pytest.mark.parametrize(
    "body",
    [
        "prompt_id: bad\nversion: '1'\nsystem: null\n",
        "prompt_id: bad\nversion: '1'\nsystem: '${missing}'\n",
    ],
)
def test_invalid_prompt_fails_during_loading(tmp_path, body):
    (tmp_path / "bad.yaml").write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        PromptRegistry(tmp_path)
