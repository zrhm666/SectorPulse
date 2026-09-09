from uuid import UUID

from sector_pulse.domain.market.quality import QualityStatus
from sector_pulse.domain.news.evidence import EvidenceLevel, EvidencePack


def test_evidence_pack_serializes_stable_level_and_counter_evidence() -> None:
    pack = EvidencePack(
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
        sector_id="BK0001",
        facts=("板块上涨 2.5%",),
        event_ids=("event-1",),
        counter_evidence=("同期大盘普涨",),
        quality_status=QualityStatus.NORMAL,
        max_level=EvidenceLevel.POSSIBLE_CATALYST,
    )

    payload = pack.model_dump(mode="json")
    assert payload["max_level"] == "POSSIBLE_CATALYST"
    assert payload["counter_evidence"] == ["同期大盘普涨"]
