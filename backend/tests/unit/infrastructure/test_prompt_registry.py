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


def test_examples_are_loaded_and_change_the_content_hash(tmp_path: Path) -> None:
    (tmp_path / "review.yaml").write_text(
        "prompt_id: review\nversion: '1'\nsystem: check\n"
        "examples:\n"
        "  - input: '{\"a\": 1}'\n"
        "    output: '{\"b\": 2}'\n",
        encoding="utf-8",
    )
    with_examples = PromptRegistry(tmp_path).get("review")
    assert [example.input for example in with_examples.examples] == ['{"a": 1}']
    assert [example.output for example in with_examples.examples] == ['{"b": 2}']

    (tmp_path / "review.yaml").write_text(
        "prompt_id: review\nversion: '1'\nsystem: check\n", encoding="utf-8"
    )
    without_examples = PromptRegistry(tmp_path).get("review")
    # 同一 system 下，示例属于提示词内容，必须改变哈希，否则审计无法区分输入。
    assert without_examples.examples == ()
    assert without_examples.content_sha256 != with_examples.content_sha256


def test_prompts_without_examples_keep_the_original_hash_algorithm(tmp_path: Path) -> None:
    import hashlib

    (tmp_path / "plain.yaml").write_text(
        "prompt_id: plain\nversion: '2'\nsystem: unchanged\n", encoding="utf-8"
    )
    prompt = PromptRegistry(tmp_path).get("plain")
    legacy = hashlib.sha256(b"plain\n2\nunchanged").hexdigest()
    assert prompt.content_sha256 == legacy


@pytest.mark.parametrize(
    "examples",
    [
        "examples: not-a-list\n",
        "examples:\n  - input: 'x'\n",
        "examples:\n  - input: ''\n    output: 'y'\n",
        "examples:\n  - input: 'x'\n    output: '   '\n",
    ],
)
def test_malformed_examples_are_rejected(tmp_path: Path, examples: str) -> None:
    (tmp_path / "bad.yaml").write_text(
        f"prompt_id: bad\nversion: '1'\nsystem: check\n{examples}", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="example"):
        PromptRegistry(tmp_path)


DEMONSTRATIONS = (
    "demonstrations:\n"
    "  - role: user\n"
    "    text: '现在该做什么？'\n"
    "  - role: assistant\n"
    "    text: '先读服务端状态。'\n"
    "    tool_name: inspect_tasks\n"
    "    tool_call_id: demo-1\n"
    "    tool_arguments: {}\n"
    "  - role: tool\n"
    "    tool_call_id: demo-1\n"
    "    text: '[]'\n"
)


def test_demonstrations_are_loaded_and_change_the_content_hash(tmp_path: Path) -> None:
    body = f"prompt_id: agent\nversion: '1'\nsystem: act\n{DEMONSTRATIONS}"
    (tmp_path / "agent.yaml").write_text(body, encoding="utf-8")
    with_demonstrations = PromptRegistry(tmp_path).get("agent")
    assert [turn.role for turn in with_demonstrations.demonstrations] == [
        "user",
        "assistant",
        "tool",
    ]
    assert with_demonstrations.demonstrations[1].tool_name == "inspect_tasks"
    assert with_demonstrations.demonstrations[1].calls_tool is True

    (tmp_path / "agent.yaml").write_text(
        "prompt_id: agent\nversion: '1'\nsystem: act\n", encoding="utf-8"
    )
    without_demonstrations = PromptRegistry(tmp_path).get("agent")
    # 示范对话属于提示词内容，必须改变哈希，否则审计无法区分调用输入。
    assert without_demonstrations.demonstrations == ()
    assert without_demonstrations.content_sha256 != with_demonstrations.content_sha256


@pytest.mark.parametrize(
    "body",
    [
        "demonstrations: not-a-list\n",
        "demonstrations:\n  - role: nobody\n    text: 'x'\n",
        "demonstrations:\n  - role: user\n    text: '   '\n",
        "demonstrations:\n  - role: user\n    text: 'x'\n    tool_name: inspect_tasks\n",
        "demonstrations:\n  - role: assistant\n    text: 'x'\n    tool_name: inspect_tasks\n",
        "demonstrations:\n  - role: assistant\n    text: 'x'\n    tool_call_id: a\n",
        "demonstrations:\n  - role: assistant\n    tool_name: t\n    tool_call_id: a\n",
        # 工具调用没有对应的结果，供应商会拒绝该请求。
        "demonstrations:\n"
        "  - role: assistant\n"
        "    text: 'x'\n"
        "    tool_name: t\n"
        "    tool_call_id: a\n"
        "  - role: tool\n"
        "    tool_call_id: b\n"
        "    text: 'r'\n",
        # 结果出现在调用之前。
        "demonstrations:\n  - role: tool\n    tool_call_id: a\n    text: 'r'\n",
        "demonstrations:\n  - role: tool\n    tool_call_id: a\n    text: 'r'\n    tool_name: t\n",
    ],
)
def test_malformed_demonstrations_are_rejected(tmp_path: Path, body: str) -> None:
    (tmp_path / "bad.yaml").write_text(
        f"prompt_id: bad\nversion: '1'\nsystem: check\n{body}", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        PromptRegistry(tmp_path)
