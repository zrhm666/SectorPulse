from pathlib import Path

from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry


def test_prompt_hash_is_stable(tmp_path: Path) -> None:
    (tmp_path / "attribution.yaml").write_text(
        "prompt_id: attribution\nversion: '1.0.0'\nsystem: test\n", encoding="utf-8"
    )
    registry = PromptRegistry(tmp_path)
    first = registry.get("attribution")
    second = registry.get("attribution")
    assert first.content_sha256 == second.content_sha256

