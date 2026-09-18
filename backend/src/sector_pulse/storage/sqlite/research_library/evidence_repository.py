"""SQLite 上已接纳内部证据的读取端。

写的还是那一批表（迁移 035 建的两张证据表 + 版本表），这里只读它们。读回来的顺序按
Artifact 引用与 `evidence_id` 排：迁移已经在 Task 3 冻结，表里没有"第几条事实"这一列，
所以顺序只能由一个稳定但内容无关的键定下来——审计要的是同一批行每次都按同一顺序出现。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence

from sector_pulse.domain.research_library.retrieval import (
    AcceptedEvidenceClaim,
    ClaimStance,
    ConflictStatus,
    EvidenceGrade,
    EvidenceSourceRef,
    InternalEvidenceClaim,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase

#: 一次查询里最多绑多少个 id。SQLite 的变量上限是 999，留出余量后分批。
_BATCH = 400


def _chunks(values: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(values[start : start + _BATCH]) for start in range(0, len(values), _BATCH))


class SQLiteAcceptedEvidenceRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def get_accepted_evidence(
        self, artifact_references: Sequence[str]
    ) -> tuple[AcceptedEvidenceClaim, ...]:
        unique = tuple(dict.fromkeys(artifact_references))
        if not unique:
            return ()
        claims: list[AcceptedEvidenceClaim] = []
        with self._database.connection() as connection:
            for batch in _chunks(unique):
                marks = ",".join("?" for _ in batch)
                rows = connection.execute(
                    "SELECT evidence_id, artifact_ref, statement, stance, conflict_status, "
                    "grade, requires_verification, qualifiers_json "
                    f"FROM internal_research_evidence WHERE artifact_ref IN ({marks}) "
                    "ORDER BY artifact_ref, evidence_id",
                    batch,
                ).fetchall()
                if not rows:
                    continue
                sources = self._sources(connection, [str(row[0]) for row in rows])
                for row in rows:
                    evidence_id = str(row[0])
                    claims.append(
                        AcceptedEvidenceClaim(
                            evidence_id=evidence_id,
                            artifact_ref=str(row[1]),
                            claim=InternalEvidenceClaim(
                                statement=str(row[2]),
                                stance=ClaimStance(row[3]),
                                conflict_status=ConflictStatus(row[4]),
                                grade=EvidenceGrade(row[5]),
                                requires_verification=bool(row[6]),
                                qualifiers=tuple(json.loads(row[7])),
                                source_refs=sources.get(evidence_id, ()),
                            ),
                        )
                    )
        return tuple(claims)

    @staticmethod
    def _sources(
        connection: sqlite3.Connection, evidence_ids: Sequence[str]
    ) -> dict[str, tuple[EvidenceSourceRef, ...]]:
        """按证据取回它引用的出处；没有出处的证据不会通过接纳，因此这里不该出现空集。"""
        grouped: dict[str, list[EvidenceSourceRef]] = {}
        for batch in _chunks(tuple(evidence_ids)):
            marks = ",".join("?" for _ in batch)
            rows = connection.execute(
                "SELECT evidence_id, document_id, document_version_id, chunk_id, page_start, "
                "page_end, section_path_json, bounding_boxes_json "
                f"FROM internal_research_evidence_sources WHERE evidence_id IN ({marks}) "
                "ORDER BY evidence_id, source_order",
                batch,
            ).fetchall()
            for row in rows:
                grouped.setdefault(str(row[0]), []).append(
                    EvidenceSourceRef(
                        document_id=str(row[1]),
                        document_version_id=str(row[2]),
                        chunk_id=str(row[3]),
                        page_start=row[4],
                        page_end=row[5],
                        section_path=tuple(json.loads(row[6])),
                        bounding_boxes=tuple(json.loads(row[7])),
                    )
                )
        return {key: tuple(value) for key, value in grouped.items()}

    def load_active_version_ids(
        self, document_version_ids: Sequence[str]
    ) -> frozenset[str]:
        unique = tuple(dict.fromkeys(document_version_ids))
        if not unique:
            return frozenset()
        active: set[str] = set()
        with self._database.connection() as connection:
            for batch in _chunks(unique):
                marks = ",".join("?" for _ in batch)
                rows = connection.execute(
                    "SELECT v.document_version_id FROM research_document_versions v "
                    "JOIN research_documents d ON d.document_id = v.document_id "
                    f"WHERE v.status = 'ACTIVE' AND d.deleted_at IS NULL "
                    f"AND v.document_version_id IN ({marks})",
                    batch,
                ).fetchall()
                active.update(str(row[0]) for row in rows)
        return frozenset(active)
