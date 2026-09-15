"""Deterministic fixture-model decisions for the production multi-agent composition."""

from __future__ import annotations

import json

from aidynamic_agent.core.message import Message, TextBlock, ToolDefinition, ToolResultBlock

from sector_pulse.infrastructure.agents.provider_factory import (
    FixtureAgentTurn,
    FixtureToolCall,
    FixtureTurnStrategy,
)
from sector_pulse.infrastructure.agents.roles import AgentRole


def _results(messages: list[Message]) -> dict[str, ToolResultBlock]:
    return {
        block.tool_call_id: block
        for message in messages
        for block in message.content
        if isinstance(block, ToolResultBlock)
    }


def _json_result(results: dict[str, ToolResultBlock], call_id: str) -> dict[str, object]:
    result = results[call_id]
    if result.is_error:
        raise RuntimeError(result.tool_result_content)
    value = json.loads(result.tool_result_content)
    if not isinstance(value, dict):
        raise ValueError(f"fixture tool result is not an object: {call_id}")
    return value


def _input_payload(messages: list[Message]) -> dict[str, object]:
    for message in messages:
        for block in message.content:
            if isinstance(block, TextBlock):
                try:
                    value = json.loads(block.text)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(value, dict) and ("goal" in value or "selected_sectors" in value):
                    return value
    return {}


def _single_ref(payload: dict[str, object], label: str) -> str:
    refs = payload.get("artifact_refs")
    if not isinstance(refs, list) or len(refs) != 1 or not isinstance(refs[0], str):
        raise ValueError(f"fixture {label} result is incomplete")
    return refs[0]


def _a0_strategy(
    messages: list[Message], tools: list[ToolDefinition] | None
) -> FixtureAgentTurn:
    del tools
    results = _results(messages)
    payload = _input_payload(messages)
    selected = payload.get("selected_sectors")
    if isinstance(selected, list) and selected:
        run_id = payload.get("run_id")
        if not isinstance(run_id, str):
            raise ValueError("fixture run identity is missing")
        return _a0_after_selection(results, selected, run_id, payload)
    if "fixture-delegate-a1" not in results:
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-delegate-a1",
                    tool_name="delegate",
                    tool_input={
                        "role": "A1",
                        "goal": "采集行情、检查质量、生成候选并提交给用户选择",
                        "scope": "data-preparation",
                        "artifact_refs": [],
                    },
                ),
            )
        )
    if "fixture-request-selection" not in results:
        child = _json_result(results, "fixture-delegate-a1")
        proposal_ref = child.get("proposal_ref")
        if not isinstance(proposal_ref, str):
            raise ValueError("A1 fixture result did not return a proposal reference")
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-request-selection",
                    tool_name="request_selection",
                    tool_input={"proposal_ref": proposal_ref},
                ),
            )
        )
    return FixtureAgentTurn(text="等待用户确认候选板块")


def _a0_after_selection(
    results: dict[str, ToolResultBlock],
    selected: list[object],
    run_id: str,
    payload: dict[str, object],
) -> FixtureAgentTurn:
    raw_refs = payload.get("research_artifact_refs", [])
    refs = raw_refs if isinstance(raw_refs, list) else []
    artifacts = [{"artifact_id": ref, "kind": "candidate_batch"} for ref in refs]
    research_inputs = [
        str(item["artifact_id"])
        for item in artifacts
        if item.get("kind") in {"candidate_batch", "news_batch"}
    ]
    selection_refs = [
        str(item["artifact_id"])
        for item in artifacts
        if item.get("kind") == "candidate_selection"
    ]
    if len(selection_refs) != 1 or not research_inputs:
        raise ValueError("fixture selection context is incomplete")

    normalized: list[dict[str, str]] = []
    for item in selected:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(key), str) for key in ("sector_id", "kind", "name")
        ):
            raise ValueError("fixture selected sector is invalid")
        normalized.append(
            {
                "sector_id": str(item["sector_id"]),
                "kind": str(item["kind"]),
                "name": str(item["name"]),
            }
        )

    a2_ids = [f"fixture-delegate-a2-{index}" for index in range(len(normalized))]
    if not all(call_id in results for call_id in a2_ids):
        return FixtureAgentTurn(
            tool_calls=tuple(
                FixtureToolCall(
                    tool_call_id=a2_ids[index],
                    tool_name="delegate",
                    tool_input={
                        "role": "A2",
                        "goal": "核验当前板块证据并提交保守归因卡",
                        "scope": f"sector:{item['kind']}:{item['sector_id']}",
                        "artifact_refs": research_inputs,
                    },
                )
                for index, item in enumerate(normalized)
            )
        )
    analysis_refs = [
        _single_ref(_json_result(results, call_id), "analysis") for call_id in a2_ids
    ]

    if "fixture-delegate-a3" not in results:
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-delegate-a3",
                    tool_name="delegate",
                    tool_input={
                        "role": "A3",
                        "goal": json.dumps(
                            {"selected_sectors": normalized}, ensure_ascii=False
                        ),
                        "scope": f"article:{run_id}",
                        "artifact_refs": [selection_refs[0], *analysis_refs],
                    },
                ),
            )
        )
    draft = _json_result(results, "fixture-delegate-a3")
    draft_ref = _single_ref(draft, "draft")
    draft_id = draft.get("draft_id")
    if not isinstance(draft_id, str):
        raise ValueError("fixture draft identity is missing")

    if "fixture-delegate-a4" not in results:
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-delegate-a4",
                    tool_name="delegate",
                    tool_input={
                        "role": "A4",
                        "goal": "独立检查草稿规则并提交审校结论",
                        "scope": f"review:{draft_id}:1",
                        "artifact_refs": [draft_ref],
                    },
                ),
            )
        )
    review = _json_result(results, "fixture-delegate-a4")
    rules_ref = review.get("rules_ref")
    review_ref = review.get("review_ref")
    if not isinstance(rules_ref, str) or not isinstance(review_ref, str):
        raise ValueError("fixture review result is incomplete")

    if "fixture-request-finish" not in results:
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-request-finish",
                    tool_name="request_finish",
                    tool_input={
                        "artifact_refs": [
                            selection_refs[0],
                            *analysis_refs,
                            draft_ref,
                            rules_ref,
                            review_ref,
                        ]
                    },
                ),
            )
        )
    return FixtureAgentTurn(text="分析、写作和独立审校已完成，等待人工审核")


def _a1_strategy(
    messages: list[Message], tools: list[ToolDefinition] | None
) -> FixtureAgentTurn:
    del tools
    results = _results(messages)
    if "fixture-collect-market" not in results:
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-collect-market",
                    tool_name="collect_market",
                    tool_input={"kinds": ["INDUSTRY", "CONCEPT"]},
                ),
            )
        )

    market = _json_result(results, "fixture-collect-market")
    market_refs = market.get("artifact_refs")
    if not isinstance(market_refs, list) or len(market_refs) != 2 or not all(
        isinstance(item, str) for item in market_refs
    ):
        raise ValueError("fixture market collection did not return two artifacts")
    quality_ids = tuple(f"fixture-quality-{index}" for index in range(2))
    if not all(call_id in results for call_id in quality_ids):
        return FixtureAgentTurn(
            tool_calls=tuple(
                FixtureToolCall(
                    tool_call_id=quality_ids[index],
                    tool_name="inspect_data_quality",
                    tool_input={"artifact_ref": artifact_ref},
                )
                for index, artifact_ref in enumerate(market_refs)
            )
        )
    for call_id in quality_ids:
        _json_result(results, call_id)

    if "fixture-rank-candidates" not in results:
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-rank-candidates",
                    tool_name="rank_sector_candidates",
                    tool_input={"market_artifact_refs": market_refs},
                ),
            )
        )
    ranked = _json_result(results, "fixture-rank-candidates")
    candidate_refs = ranked.get("artifact_refs")
    summary = ranked.get("summary")
    if (
        not isinstance(candidate_refs, list)
        or len(candidate_refs) != 1
        or not isinstance(candidate_refs[0], str)
        or not isinstance(summary, dict)
    ):
        raise ValueError("fixture ranking result is incomplete")

    if "fixture-collect-news" not in results:
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-collect-news",
                    tool_name="collect_initial_news",
                    tool_input={
                        "candidate_artifact_ref": candidate_refs[0],
                        "reason": "INITIAL_CANDIDATES",
                    },
                ),
            )
        )
    # Initial news may be degraded in an offline fixture. Candidate proposal is
    # still valid because its deterministic ranking artifact is already persisted.

    if "fixture-propose-candidates" not in results:
        candidates = summary.get("candidates")
        if not isinstance(candidates, list) or len(candidates) < 3:
            raise ValueError("fixture ranking produced fewer than three candidates")
        proposals = []
        for item in candidates:
            if not isinstance(item, dict) or not isinstance(item.get("sector_id"), str):
                raise ValueError("fixture candidate is invalid")
            proposals.append(
                {
                    "sector_id": item["sector_id"],
                    "explanation": "基于固定评分、数据质量和新闻覆盖进入候选",
                }
            )
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-propose-candidates",
                    tool_name="propose_candidates",
                    tool_input={
                        "candidate_artifact_ref": candidate_refs[0],
                        "proposals": proposals,
                    },
                ),
            )
        )

    proposal = _json_result(results, "fixture-propose-candidates")
    proposal_refs = proposal.get("artifact_refs")
    if (
        not isinstance(proposal_refs, list)
        or len(proposal_refs) != 1
        or not isinstance(proposal_refs[0], str)
    ):
        raise ValueError("fixture proposal result is incomplete")
    return FixtureAgentTurn(
        text=json.dumps(
            {"status": "awaiting_user_selection", "proposal_ref": proposal_refs[0]},
            ensure_ascii=False,
        )
    )


def _a2_strategy(
    messages: list[Message], tools: list[ToolDefinition] | None
) -> FixtureAgentTurn:
    del tools
    results = _results(messages)
    payload = _input_payload(messages)
    refs = payload.get("artifact_refs")
    if not isinstance(refs, list) or not refs or not all(isinstance(item, str) for item in refs):
        raise ValueError("fixture A2 input artifacts are missing")
    if "fixture-inspect-evidence" not in results:
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-inspect-evidence",
                    tool_name="inspect_evidence",
                    tool_input={"artifact_ids": refs},
                ),
            )
        )
    inspection = _json_result(results, "fixture-inspect-evidence")
    inspection_ref = _single_ref(inspection, "inspection")
    if "fixture-submit-analysis" not in results:
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-submit-analysis",
                    tool_name="submit_analysis",
                    tool_input={
                        "inspection_artifact_id": inspection_ref,
                        "submission": {
                            "attribution_level": "NO_RELIABLE_EXPLANATION",
                            "confidence": "0.2",
                            "conclusion": "当前证据不足以形成可靠因果解释",
                            "supporting_evidence_ids": [],
                            "uncertainties": ["缺少可验证的直接驱动证据"],
                            "background_event_ids": [],
                            "claims": [],
                            "forbidden_inferences": [],
                        },
                    },
                ),
            )
        )
    analysis = _json_result(results, "fixture-submit-analysis")
    return FixtureAgentTurn(text=json.dumps(analysis, ensure_ascii=False))


def _a3_strategy(
    messages: list[Message], tools: list[ToolDefinition] | None
) -> FixtureAgentTurn:
    del tools
    results = _results(messages)
    payload = _input_payload(messages)
    raw_goal = payload.get("goal")
    try:
        goal = json.loads(raw_goal) if isinstance(raw_goal, str) else {}
    except json.JSONDecodeError:
        goal = {}
    selected = goal.get("selected_sectors") if isinstance(goal, dict) else None
    if not isinstance(selected, list) or len(selected) < 3:
        raise ValueError("fixture A3 selected sectors are missing")
    sectors = [item for item in selected if isinstance(item, dict)]
    sector_ids = [str(item["sector_id"]) for item in sectors]
    if "fixture-submit-outline" not in results:
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-submit-outline",
                    tool_name="submit_outline",
                    tool_input={
                        "submission": {
                            "sector_ids": sector_ids,
                            "order_reasons": {
                                sector_id: "按固定候选排名组织" for sector_id in sector_ids
                            },
                            "title_directions": ["板块异动背后的证据边界"],
                            "thesis": "区分市场表现、可能催化与尚不可验证的因果解释",
                            "section_character_budgets": {
                                sector_id: 360 for sector_id in sector_ids
                            },
                            "excluded_sector_reasons": {},
                        }
                    },
                ),
            )
        )
    outline = _json_result(results, "fixture-submit-outline")
    outline_ref = _single_ref(outline, "outline")
    if "fixture-submit-draft" not in results:
        sections = []
        for index, item in enumerate(sectors):
            sector_id = str(item["sector_id"])
            name = str(item["name"])
            sentence = (
                f"{name}是本节观察主体，固定行情显示其相对表现靠前，但价格变化本身不能证明因果。"
                "当前材料主要用于说明市场强弱和数据边界，尚缺少能够交叉验证的直接驱动证据。"
                "研究结论因此保持保守：把可复核的行情事实与解释性判断分开，并明确记录信息截止时间。"
                "后续若出现权威披露、可靠媒体报道或可验证正文，应重新检查事件时间、主体映射和反证。"
            )
            body = sentence + sentence
            sections.append(
                {
                    "section_id": f"section-{index + 1}",
                    "sector_id": sector_id,
                    "heading": f"{name}：表现与证据边界",
                    "body": body,
                    "claims": [],
                    "source_ids": [],
                }
            )
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-submit-draft",
                    tool_name="submit_draft",
                    tool_input={
                        "outline_artifact_id": outline_ref,
                        "submission": {
                            "titles": ["板块异动背后的证据边界"],
                            "introduction": (
                                "本文基于固定样例梳理板块表现，并严格区分事实、关联与因果解释。"
                            ),
                            "sections": sections,
                            "conclusion": "现有材料适合形成观察清单，不足以支持确定性的驱动结论。",
                            "risk_notice": (
                                "本文仅作研究记录，不构成任何投资建议；市场变化可能使结论失效。"
                            ),
                        },
                    },
                ),
            )
        )
    draft = _json_result(results, "fixture-submit-draft")
    return FixtureAgentTurn(text=json.dumps(draft, ensure_ascii=False))


def _a4_strategy(
    messages: list[Message], tools: list[ToolDefinition] | None
) -> FixtureAgentTurn:
    del tools
    results = _results(messages)
    payload = _input_payload(messages)
    refs = payload.get("artifact_refs")
    if not isinstance(refs, list) or len(refs) != 1 or not isinstance(refs[0], str):
        raise ValueError("fixture A4 draft artifact is missing")
    draft_ref = refs[0]
    if "fixture-check-rules" not in results:
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-check-rules",
                    tool_name="check_draft_rules",
                    tool_input={"draft_artifact_id": draft_ref},
                ),
            )
        )
    rules = _json_result(results, "fixture-check-rules")
    rules_ref = _single_ref(rules, "rules")
    if "fixture-submit-review" not in results:
        return FixtureAgentTurn(
            tool_calls=(
                FixtureToolCall(
                    tool_call_id="fixture-submit-review",
                    tool_name="submit_review",
                    tool_input={
                        "draft_artifact_id": draft_ref,
                        "rules_artifact_id": rules_ref,
                        "submission": {"decision": "REVISE", "issues": []},
                    },
                ),
            )
        )
    review = _json_result(results, "fixture-submit-review")
    review_ref = _single_ref(review, "review")
    return FixtureAgentTurn(
        text=json.dumps(
            {"rules_ref": rules_ref, "review_ref": review_ref}, ensure_ascii=False
        )
    )


def default_fixture_strategies() -> dict[AgentRole, FixtureTurnStrategy]:
    return {
        AgentRole.A0: _a0_strategy,
        AgentRole.A1: _a1_strategy,
        AgentRole.A2: _a2_strategy,
        AgentRole.A3: _a3_strategy,
        AgentRole.A4: _a4_strategy,
    }
