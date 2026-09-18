"""已接纳证据的读取端必须在 JSONB 上活着（规格 16.1）。

本仓库跑不起真正的 PostgreSQL（没有配置专用测试库，合约用例整体跳过），但这个缺陷不需要
数据库就能复现：出错的地方是"这一列的值已经是 `list` 了，还要不要再 `json.loads` 一次"。
迁移 035 把 `qualifiers_json`、`section_path_json`、`bounding_boxes_json` 转成了 JSONB，而
psycopg 3 对 JSONB 返回的是已经解析好的对象，所以答案是"不要"——多解析一次就是对着 `list`
调用，抛 `TypeError`。

喂一个驱动形状的假连接就能走完真实的读取代码：行里的 `*_json` 列是 `list` 而不是字符串。
SQLite 那一侧读的是 TEXT，显式解析才对，所以同一份读取逻辑必须两种形状都能接住。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sector_pulse.storage.postgres.research_library.evidence_repository import (
    PostgresAcceptedEvidenceRepository,
)

_EVIDENCE_ID = "ev_1"
_ARTIFACT_REF = "artifact://internal/1"


class _FakeRows:
    """`Result` 里读取端真正用到的两个方法。"""

    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeRows:
        return self

    def all(self) -> list[Mapping[str, Any]]:
        return list(self._rows)

    def fetchall(self) -> list[Mapping[str, Any]]:
        return list(self._rows)


class _FakeConnection:
    """按语句挑结果：读取端只发两条 SELECT，第二条是来源表。"""

    def __init__(
        self, *, claims: Sequence[Mapping[str, Any]], sources: Sequence[Mapping[str, Any]]
    ) -> None:
        self._claims = claims
        self._sources = sources

    def execute(self, statement: Any, parameters: Any = None) -> _FakeRows:
        if "internal_research_evidence_sources" in str(statement):
            return _FakeRows(self._sources)
        return _FakeRows(self._claims)

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *exception: object) -> bool:
        return False


class _FakeDatabase:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def start(self) -> _FakeDatabase:
        return self

    def connect(self) -> _FakeConnection:
        return self._connection


def _claim_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "evidence_id": _EVIDENCE_ID,
        "artifact_ref": _ARTIFACT_REF,
        "statement": "电解液价格在二季度环比回升",
        "stance": "supporting",
        "conflict_status": "NOT_CONFLICT",
        "grade": "PRIMARY_SOURCE",
        "requires_verification": 0,
        "qualifiers_json": [],
    }
    row.update(overrides)
    return row


def _source_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "evidence_id": _EVIDENCE_ID,
        "document_id": "doc_1",
        "document_version_id": "ver_1",
        "chunk_id": "chk_1",
        "page_start": 3,
        "page_end": 4,
        "section_path_json": [],
        "bounding_boxes_json": [],
    }
    row.update(overrides)
    return row


def _read(claims: Sequence[Mapping[str, Any]], sources: Sequence[Mapping[str, Any]]):
    repository = PostgresAcceptedEvidenceRepository(
        _FakeDatabase(_FakeConnection(claims=claims, sources=sources))  # type: ignore[arg-type]
    )
    return repository.get_accepted_evidence((_ARTIFACT_REF,))


def test_a_driver_parsed_jsonb_value_is_read_without_parsing_it_again() -> None:
    """JSONB 列到达读取端时已经是 list —— 这是 PostgreSQL 上的常态，不是边角。"""
    claims = _read(
        claims=[
            _claim_row(qualifiers_json=["含税", "华东"]),
        ],
        sources=[
            _source_row(
                section_path_json=["3 成本", "3.1 电解液"],
                bounding_boxes_json=[[1.0, 2.0, 3.0, 4.0]],
            )
        ],
    )

    assert len(claims) == 1
    assert claims[0].claim.qualifiers == ("含税", "华东")
    source = claims[0].claim.source_refs[0]
    assert source.section_path == ("3 成本", "3.1 电解液")
    assert source.bounding_boxes == ((1.0, 2.0, 3.0, 4.0),)


def test_a_text_column_is_still_parsed() -> None:
    """SQLite 读的是 TEXT，同一份代码不能为了修 JSONB 就把解析整个删掉。"""
    claims = _read(
        claims=[_claim_row(qualifiers_json='["含税"]')],
        sources=[_source_row(section_path_json='["3 成本"]', bounding_boxes_json="[]")],
    )

    assert claims[0].claim.qualifiers == ("含税",)
    assert claims[0].claim.source_refs[0].section_path == ("3 成本",)


def test_an_empty_jsonb_column_reads_as_empty_not_as_an_error() -> None:
    """列默认值就是 `'[]'::jsonb`：每一行都带空数组，读取端不能因此崩。"""
    claims = _read(claims=[_claim_row()], sources=[_source_row()])

    assert claims[0].claim.qualifiers == ()
    assert claims[0].claim.source_refs[0].bounding_boxes == ()
