from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.real_data_run import (
    RealDataCandidate,
    RealDataRun,
    RealDataRunRequest,
)
from sector_pulse.storage.operations_query import SQLiteOperationsQuery
from sector_pulse.storage.phase1b_runs_repository import (
    Phase1BRunRow,
    SQLitePhase1BRunsRepository,
)
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.sqlite import SQLiteDatabase


def test_sqlite_operations_query_unifies_real_persisted_runs(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "operations-query.db")
    database.initialize()
    content_repository = SQLitePhase1BRunsRepository(database)
    data_repository = SQLiteRealDataRunRepository(database)
    requested_at = datetime(2026, 8, 27, 9, tzinfo=UTC)
    content_id = uuid4()
    content_repository.insert(
        Phase1BRunRow(
            run_id=content_id,
            requested_at=requested_at,
            provider="fixture",
            status="READY_FOR_HUMAN_REVIEW",
            elapsed_ms=1500,
            total_cost_cny="0.25",
            finished_at=requested_at + timedelta(seconds=2),
        )
    )
    data_run = RealDataRun(
        request=RealDataRunRequest(
            mode="post_close", requested_at=requested_at + timedelta(minutes=1)
        ),
        provider="live",
    )
    data_repository.insert(data_run)
    data_repository.save_candidates(
        data_run.run_id,
        (
            RealDataCandidate(
                sector_id="industry-1",
                sector_kind=SectorKind.INDUSTRY,
                rank=1,
                score=Decimal("9.5"),
            ),
            RealDataCandidate(
                sector_id="industry-2",
                sector_kind=SectorKind.INDUSTRY,
                rank=2,
                score=Decimal("8.0"),
            ),
        ),
    )

    records = SQLiteOperationsQuery(database).list_records()

    assert [record.run_id for record in records] == [
        str(data_run.run_id),
        str(content_id),
    ]
    assert records[0].kind == "data"
    assert records[0].mode == "盘后复盘"
    assert records[0].candidate_count == 2
    assert records[1].kind == "content"
    assert records[1].mode == "内容生成"
    assert records[1].total_cost_cny == Decimal("0.25")
    assert records[1].candidate_count == 0


def test_sqlite_operations_query_applies_since_and_limit(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "operations-window.db")
    database.initialize()
    repository = SQLitePhase1BRunsRepository(database)
    now = datetime(2026, 8, 27, 12, tzinfo=UTC)
    for requested_at in (now - timedelta(days=2), now - timedelta(hours=1), now):
        repository.insert(
            Phase1BRunRow(
                run_id=uuid4(),
                requested_at=requested_at,
                provider="fixture",
                status="RUNNING",
            )
        )

    records = SQLiteOperationsQuery(database).list_records(
        since=now - timedelta(days=1), limit=1
    )

    assert len(records) == 1
    assert records[0].requested_at == now


def test_sqlite_operations_query_does_not_count_one_workflow_twice(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "operations-deduplication.db")
    database.initialize()
    content_repository = SQLitePhase1BRunsRepository(database)
    data_repository = SQLiteRealDataRunRepository(database)
    run_id = uuid4()
    requested_at = datetime(2026, 8, 27, 12, tzinfo=UTC)
    data_repository.insert(
        RealDataRun(
            run_id=run_id,
            request=RealDataRunRequest(
                mode="post_close", requested_at=requested_at
            ),
            provider="live",
        )
    )
    content_repository.insert(
        Phase1BRunRow(
            run_id=run_id,
            requested_at=requested_at,
            provider="live",
            status="RUNNING",
        )
    )

    records = SQLiteOperationsQuery(database).list_records()

    assert len(records) == 1
    assert records[0].kind == "content"
