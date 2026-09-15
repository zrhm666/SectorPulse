from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.runs.real_data_run import (
    RealDataCandidate,
    RealDataRun,
    RealDataRunRequest,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.operations_query import SQLiteOperationsQuery
from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository
from sector_pulse.storage.sqlite.runs.phase1b_runs_repository import (
    Phase1BRunRow,
    SQLitePhase1BRunsRepository,
)
from sector_pulse.storage.sqlite.runs.real_data_run_repository import SQLiteRealDataRunRepository


def _query(database: SQLiteDatabase) -> SQLiteOperationsQuery:
    return SQLiteOperationsQuery(database, SQLiteOrchestrationRepository(database))


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

    records = _query(database).list_records()

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

    records = _query(database).list_records(
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

    records = _query(database).list_records()

    assert len(records) == 1
    assert records[0].kind == "content"


def test_sqlite_operations_query_counts_multi_agent_runs_without_inventing_cost(tmp_path) -> None:
    from sector_pulse.domain.orchestration.models import (
        BudgetLedger,
        BudgetReservation,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    database = SQLiteDatabase(tmp_path / "operations-multi-agent.db")
    database.initialize()
    requested_at = datetime(2026, 8, 27, 12, tzinfo=UTC)
    run_id = uuid4()
    snapshot = RunSnapshot(
        run_id=run_id,
        requested_at=requested_at,
        deadline=requested_at + timedelta(minutes=10),
        tasks=(
            TaskRecord(
                task_id=uuid4(),
                role="A0",
                scope="分析半导体板块",
                status=TaskStatus.WAITING_USER_REVIEW,
            ),
        ),
        ledger=BudgetLedger(
            reservations=(BudgetReservation(call_id="m1", reserved_tokens=10),),
        ),
    )
    SQLiteOrchestrationRepository(database).save(snapshot, -1, "run.created")

    records = _query(database).list_records()

    assert [record.run_id for record in records] == [str(run_id)]
    record = records[0]
    assert record.execution_engine == "multi_agent"
    assert record.kind == "content"
    assert record.requested_at == requested_at
    assert record.status == "WAITING_USER_REVIEW"
    assert record.total_cost_cny is None


def test_sqlite_operations_query_prefers_the_multi_agent_snapshot_over_legacy_rows(
    tmp_path,
) -> None:
    from sector_pulse.domain.orchestration.models import RunSnapshot, TaskRecord, TaskStatus
    database = SQLiteDatabase(tmp_path / "operations-multi-agent-precedence.db")
    database.initialize()
    requested_at = datetime(2026, 8, 27, 12, tzinfo=UTC)
    run_id = uuid4()
    SQLiteRealDataRunRepository(database).insert(
        RealDataRun(
            run_id=run_id,
            request=RealDataRunRequest(mode="post_close", requested_at=requested_at),
            provider="live",
        )
    )
    SQLiteOrchestrationRepository(database).save(
        RunSnapshot(
            run_id=run_id,
            requested_at=requested_at,
            deadline=requested_at + timedelta(minutes=10),
            tasks=(
                TaskRecord(
                    task_id=uuid4(),
                    role="A0",
                    scope="分析半导体板块",
                    status=TaskStatus.RUNNING,
                    worker_id="root-agent-1",
                    lease_expires_at=requested_at + timedelta(minutes=5),
                ),
            ),
        ),
        -1,
        "run.created",
    )

    records = _query(database).list_records()

    assert len(records) == 1
    assert records[0].execution_engine == "multi_agent"
    assert records[0].status == "RUNNING"
