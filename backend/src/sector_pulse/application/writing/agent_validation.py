import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from sector_pulse.domain.writing.attribution import (
    LEVEL_RANK,
    AttributionContext,
    AttributionGateResult,
    Claim,
    SectorAnalysisCard,
)


class AgentOutputViolation(ValueError):
    def __init__(self, code: str, message: str, location: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.location = location


def validate_analysis_card(
    card: SectorAnalysisCard,
    gate: AttributionGateResult,
    context: AttributionContext,
) -> SectorAnalysisCard:
    allowed_ids = set(gate.eligible_evidence_ids) | set(gate.excluded_evidence_ids)
    for evidence_id in card.supporting_evidence_ids:
        if evidence_id not in allowed_ids:
            raise AgentOutputViolation("UNKNOWN_EVIDENCE_ID", evidence_id)
    if card.run_id != context.run_id or card.sector_id != context.sector_id:
        raise AgentOutputViolation("CARD_CONTEXT_MISMATCH", "card does not match context")
    if LEVEL_RANK[card.attribution_level] > LEVEL_RANK[gate.allowed_max_level]:
        raise AgentOutputViolation("ATTRIBUTION_LEVEL_EXCEEDED", card.attribution_level.value)
    validate_prohibited_language(card.conclusion)
    for claim in card.claims:
        validate_prohibited_language(claim.text)
        validate_claim_numbers(claim, context.market_facts)
    return card


def _numbers(text: str) -> tuple[Decimal, ...]:
    values: list[Decimal] = []
    for raw in re.findall(r"[-+]?\d+(?:\.\d+)?", text):
        try:
            values.append(Decimal(raw))
        except InvalidOperation:
            continue
    return tuple(values)


def validate_claim_numbers(claim: Claim, market_facts: Mapping[str, object]) -> Claim:
    for fact_key in claim.fact_keys:
        value = market_facts.get(fact_key)
        if not isinstance(value, Decimal):
            continue
        if any(number != value for number in _numbers(claim.text)):
            raise AgentOutputViolation("MARKET_NUMBER_MISMATCH", fact_key)
    return claim


def validate_prohibited_language(text: str) -> str:
    prohibited = ("建议重仓", "建议买入", "必涨", "稳赚", "确定性收益", "目标价")
    if any(term in text for term in prohibited):
        raise AgentOutputViolation("PROHIBITED_INVESTMENT_LANGUAGE", text)
    return text
