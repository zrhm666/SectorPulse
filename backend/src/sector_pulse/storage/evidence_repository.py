import hashlib
from collections.abc import Sequence

from sector_pulse.domain.evidence import EvidencePack
from sector_pulse.storage.sqlite import SQLiteDatabase


class SQLiteEvidenceRepository:
    """保存证据包的结构化 JSON 和哈希，不保存模型原始响应。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def save(self, packs: Sequence[EvidencePack]) -> None:
        with self._database.transaction() as connection:
            for pack in packs:
                payload = pack.model_dump_json()
                connection.execute(
                    """
                    INSERT INTO evidence_packs (
                        run_id, provider_sector_id, sector_kind, quality_status,
                        payload_json, payload_hash
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, provider_sector_id, sector_kind) DO UPDATE SET
                        quality_status = excluded.quality_status,
                        payload_json = excluded.payload_json,
                        payload_hash = excluded.payload_hash
                    """,
                    (
                        str(pack.run_id),
                        pack.sector_id,
                        pack.sector_kind.value,
                        pack.quality_status.value,
                        payload,
                        hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                    ),
                )
