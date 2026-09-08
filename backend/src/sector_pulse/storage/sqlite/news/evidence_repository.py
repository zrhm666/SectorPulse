import hashlib
from collections.abc import Sequence
from uuid import UUID

from sector_pulse.domain.news.evidence import EvidencePack
from sector_pulse.storage.sqlite.database import SQLiteDatabase


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

    def list_for_run(self, run_id: UUID) -> tuple[EvidencePack, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM evidence_packs WHERE run_id = ? "
                "ORDER BY sector_kind, provider_sector_id",
                (str(run_id),),
            ).fetchall()
        return tuple(EvidencePack.model_validate_json(row[0]) for row in rows)
