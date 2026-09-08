import hashlib
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.evidence import EvidencePack
from sector_pulse.storage.postgres.database import PostgresDatabase


class PostgresEvidenceRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save(self, packs: Sequence[EvidencePack]) -> None:
        with self._database.start().begin() as connection:
            for pack in packs:
                payload = pack.model_dump_json()
                connection.execute(
                    text(
                        """INSERT INTO evidence_packs
                        (run_id, provider_sector_id, sector_kind, quality_status,
                         payload_json, payload_hash)
                        VALUES (:run_id, :sector_id, :sector_kind, :quality_status,
                         :payload_json, :payload_hash)
                        ON CONFLICT (run_id, provider_sector_id, sector_kind)
                        DO UPDATE SET quality_status = EXCLUDED.quality_status,
                         payload_json = EXCLUDED.payload_json,
                         payload_hash = EXCLUDED.payload_hash"""
                    ),
                    {
                        "run_id": str(pack.run_id), "sector_id": pack.sector_id,
                        "sector_kind": pack.sector_kind.value,
                        "quality_status": pack.quality_status.value,
                        "payload_json": payload,
                        "payload_hash": hashlib.sha256(payload.encode()).hexdigest(),
                    },
                )

    def list_for_run(self, run_id: UUID) -> tuple[EvidencePack, ...]:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text(
                    "SELECT payload_json FROM evidence_packs WHERE run_id = :run_id "
                    "ORDER BY sector_kind, provider_sector_id"
                ),
                {"run_id": str(run_id)},
            )
            rows = result.fetchall()
        return tuple(EvidencePack.model_validate_json(row[0]) for row in rows)
