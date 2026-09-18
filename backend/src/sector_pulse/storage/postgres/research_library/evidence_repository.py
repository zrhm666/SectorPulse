"""PostgreSQL 上已接纳内部证据的读取端。

与 SQLite 实现读同一批表，差别只在绑定批量参数的方式。顺序同样按 Artifact 引用与
`evidence_id` 排：迁移 035 里没有"第几条事实"这一列，而它已经在 Task 3 冻结。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from sector_pulse.domain.research_library.retrieval import (
    AcceptedEvidenceClaim,
    ClaimStance,
    ConflictStatus,
    EvidenceGrade,
    EvidenceSourceRef,
    InternalEvidenceClaim,
)
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.research_library.json_columns import payload

#: 一次查询里最多绑多少个 id，避免超出驱动的参数上限。
_BATCH = 400

_SELECT_CLAIMS = (
    "SELECT evidence_id, artifact_ref, statement, stance, conflict_status, grade, "
    "requires_verification, qualifiers_json FROM internal_research_evidence "
    "WHERE artifact_ref = ANY(CAST(:refs AS TEXT[])) ORDER BY artifact_ref, evidence_id"
)
_SELECT_SOURCES = (
    "SELECT evidence_id, document_id, document_version_id, chunk_id, page_start, page_end, "
    "section_path_json, bounding_boxes_json FROM internal_research_evidence_sources "
    "WHERE evidence_id = ANY(CAST(:ids AS TEXT[])) ORDER BY evidence_id, source_order"
)
#: `JOIN ... deleted_at IS NULL`：软删除不改版本行的状态（规格 16.3 第 1 步只写文档行），
#: 因此"这一版还生效吗"必须在这一句里把已删除文档名下的版本排除掉。少了它，已接纳的证据会
#: 在资料被删除之后继续被判定为可引用。
_SELECT_ACTIVE = (
    "SELECT v.document_version_id FROM research_document_versions v "
    "JOIN research_documents d ON d.document_id = v.document_id "
    "WHERE v.status = 'ACTIVE' AND d.deleted_at IS NULL "
    "AND v.document_version_id = ANY(CAST(:ids AS TEXT[]))"
)


def _chunks(values: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(values[start : start + _BATCH]) for start in range(0, len(values), _BATCH))


class PostgresAcceptedEvidenceRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def _connect(self) -> Connection:
        return self._database.start().connect()

    def get_accepted_evidence(
        self, artifact_references: Sequence[str]
    ) -> tuple[AcceptedEvidenceClaim, ...]:
        unique = tuple(dict.fromkeys(artifact_references))
        if not unique:
            return ()
        claims: list[AcceptedEvidenceClaim] = []
        with self._connect() as connection:
            for batch in _chunks(unique):
                rows = (
                    connection.execute(text(_SELECT_CLAIMS), {"refs": list(batch)}).mappings().all()
                )
                if not rows:
                    continue
                sources = self._sources(connection, tuple(str(row["evidence_id"]) for row in rows))
                for row in rows:
                    evidence_id = str(row["evidence_id"])
                    claims.append(
                        AcceptedEvidenceClaim(
                            evidence_id=evidence_id,
                            artifact_ref=str(row["artifact_ref"]),
                            claim=InternalEvidenceClaim(
                                statement=str(row["statement"]),
                                stance=ClaimStance(row["stance"]),
                                conflict_status=ConflictStatus(row["conflict_status"]),
                                grade=EvidenceGrade(row["grade"]),
                                requires_verification=bool(row["requires_verification"]),
                                qualifiers=tuple(payload(row["qualifiers_json"])),
                                source_refs=sources.get(evidence_id, ()),
                            ),
                        )
                    )
        return tuple(claims)

    @staticmethod
    def _sources(
        connection: Connection, evidence_ids: Sequence[str]
    ) -> dict[str, tuple[EvidenceSourceRef, ...]]:
        grouped: dict[str, list[EvidenceSourceRef]] = {}
        for batch in _chunks(tuple(evidence_ids)):
            rows = connection.execute(text(_SELECT_SOURCES), {"ids": list(batch)}).mappings().all()
            for row in rows:
                grouped.setdefault(str(row["evidence_id"]), []).append(
                    EvidenceSourceRef(
                        document_id=str(row["document_id"]),
                        document_version_id=str(row["document_version_id"]),
                        chunk_id=str(row["chunk_id"]),
                        page_start=row["page_start"],
                        page_end=row["page_end"],
                        section_path=tuple(payload(row["section_path_json"])),
                        bounding_boxes=tuple(payload(row["bounding_boxes_json"])),
                    )
                )
        return {key: tuple(value) for key, value in grouped.items()}

    def load_active_version_ids(self, document_version_ids: Sequence[str]) -> frozenset[str]:
        unique = tuple(dict.fromkeys(document_version_ids))
        if not unique:
            return frozenset()
        active: set[str] = set()
        with self._connect() as connection:
            for batch in _chunks(unique):
                rows = connection.execute(text(_SELECT_ACTIVE), {"ids": list(batch)}).fetchall()
                active.update(str(row[0]) for row in rows)
        return frozenset(active)
