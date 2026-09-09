from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sector_pulse.domain.evaluation.shadow_acceptance import ShadowRun
from sector_pulse.domain.runs.real_data_run import RealDataRun, RealDataRunRequest
from sector_pulse.domain.runs.task import TaskRunKey, TaskRunStatus
from sector_pulse.storage.ports.evaluation import (
    PromptGoldenRepositoryPort,
    ShadowAcceptanceRepositoryPort,
)
from sector_pulse.storage.ports.market import (
    CandidateSelectionRepositoryPort,
    MarketSnapshotRepositoryPort,
)
from sector_pulse.storage.ports.news import (
    EvidenceRepositoryPort,
    NewsEvidenceRepositoryPort,
    NewsRepositoryPort,
    NewsRetrievalRepositoryPort,
)
from sector_pulse.storage.ports.operations import OperationsQueryPort
from sector_pulse.storage.ports.review import (
    DraftEditRepositoryPort,
    GovernanceRepositoryPort,
    ReleaseAuditRepositoryPort,
)
from sector_pulse.storage.ports.runs import Phase1BRunsRepositoryPort, RealDataRunRepositoryPort
from sector_pulse.storage.ports.tasks import ScheduleRepositoryPort, TaskRepositoryPort
from sector_pulse.storage.ports.writing import AgentInvocationRepositoryPort, Phase1BRepositoryPort
from sector_pulse.storage.runtime_bundle import build_sqlite_storage
from sector_pulse.storage.sqlite.database import SQLiteDatabase


def _bundle(tmp_path: Path):
    return build_sqlite_storage(SQLiteDatabase(tmp_path / "runtime.db"))


def test_sqlite_runtime_adapters_satisfy_declared_ports(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    expected = {
        "market_snapshots": MarketSnapshotRepositoryPort,
        "news": NewsRepositoryPort,
        "evidence": EvidenceRepositoryPort,
        "news_retrieval": NewsRetrievalRepositoryPort,
        "real_data_runs": RealDataRunRepositoryPort,
        "task": TaskRepositoryPort,
        "phase1b_runs": Phase1BRunsRepositoryPort,
        "phase1b": Phase1BRepositoryPort,
        "invocations": AgentInvocationRepositoryPort,
        "news_evidence": NewsEvidenceRepositoryPort,
        "draft_edit": DraftEditRepositoryPort,
        "prompt_golden": PromptGoldenRepositoryPort,
        "release_audit": ReleaseAuditRepositoryPort,
        "shadow": ShadowAcceptanceRepositoryPort,
        "governance": GovernanceRepositoryPort,
        "operations": OperationsQueryPort,
        "candidate_selections": CandidateSelectionRepositoryPort,
    }

    for field, port in expected.items():
        assert isinstance(getattr(bundle, field), port), field
    assert isinstance(bundle.task, ScheduleRepositoryPort)


def test_task_lifecycle_metadata_round_trips(tmp_path: Path) -> None:
    repository = _bundle(tmp_path).task
    assert repository is not None
    source_id = repository.create_or_get_run(
        TaskRunKey(input_fingerprint="source"), "fixture", {}
    )
    retry_id = repository.create_or_get_run(
        TaskRunKey(input_fingerprint="retry"),
        "fixture",
        {},
        retry_of_run_id=source_id,
    )
    requested_at = datetime(2026, 8, 30, 1, 2, 3, tzinfo=UTC)

    assert repository.request_cancel(retry_id, requested_at)
    detail = repository.get_task_detail(retry_id)
    assert detail is not None
    assert detail["retry_of_run_id"] == str(source_id)
    assert detail["cancel_requested_at"] == requested_at.isoformat()


def test_running_task_can_be_recovered_as_interrupted(tmp_path: Path) -> None:
    repository = _bundle(tmp_path).task
    assert repository is not None
    now = datetime(2026, 8, 30, 2, 0, tzinfo=UTC)
    run_id = repository.create_or_get_run(
        TaskRunKey(input_fingerprint="recover"), "fixture", {}
    )
    assert repository.claim_run(
        run_id,
        "lost-worker",
        now + timedelta(minutes=5),
        now=now,
    )

    assert repository.recover_interrupted(now, "process restarted") == 1
    detail = repository.get_task_detail(run_id)
    assert detail is not None
    assert detail["status"] == TaskRunStatus.INTERRUPTED.value
    assert detail["interrupted_reason"] == "process restarted"
    assert detail["heartbeat_at"] == now.isoformat()


def test_real_data_retry_source_round_trips(tmp_path: Path) -> None:
    repository = _bundle(tmp_path).real_data_runs
    source = RealDataRun(request=RealDataRunRequest(mode="intraday"))
    repository.insert(source)
    retry = RealDataRun(
        request=RealDataRunRequest(mode="intraday"),
        retry_of_run_id=source.run_id,
    )
    repository.insert(retry)

    loaded = repository.get_run(retry.run_id)
    assert loaded is not None
    assert loaded.retry_of_run_id == source.run_id


def test_shadow_run_can_be_loaded_by_identity(tmp_path: Path) -> None:
    repository = _bundle(tmp_path).shadow
    assert repository is not None
    item = ShadowRun(
        run_id=uuid4(),
        trading_date=date(2026, 8, 30),
        mode="post_close",
        created_at=datetime(2026, 8, 30, tzinfo=UTC),
    )
    repository.save_run(item)

    assert repository.get(item.shadow_id) == item
    assert repository.get(uuid4()) is None
