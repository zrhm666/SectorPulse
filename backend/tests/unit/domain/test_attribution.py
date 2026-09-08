from decimal import Decimal
from uuid import UUID

import pytest
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.news.evidence import EvidenceLevel
from sector_pulse.domain.writing.attribution import Claim, ClaimKind, SectorAnalysisCard

RUN_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_analysis_card_cannot_exceed_gate() -> None:
    with pytest.raises(ValueError, match="exceeds allowed maximum"):
        SectorAnalysisCard(
            run_id=RUN_ID,
            sector_id="industry-1",
            sector_kind=SectorKind.INDUSTRY,
            allowed_max_level=EvidenceLevel.MARKET_ASSOCIATION,
            attribution_level=EvidenceLevel.POSSIBLE_CATALYST,
            confidence=Decimal("0.70"),
            conclusion="消息可能催化板块",
            supporting_evidence_ids=("event-1",),
            counter_evidence=(),
            uncertainties=("缺少直接因果表述",),
            background_event_ids=(),
            claims=(),
            forbidden_inferences=(),
        )


def test_claim_is_immutable_and_typed() -> None:
    claim = Claim(
        claim_id="claim-1",
        kind=ClaimKind.MARKET_FACT,
        text="板块上涨3.2%",
        fact_keys=("pct_change",),
    )
    assert claim.model_config["frozen"] is True
