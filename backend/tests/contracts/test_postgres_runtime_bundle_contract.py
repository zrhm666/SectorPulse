import inspect

import sector_pulse.storage.runtime_bundle as runtime_bundle
from sector_pulse.storage.ports import (
    OperationsQueryPort,
    RuntimeTaskRepositoryPort,
)
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_operations_query import PostgresOperationsQuery
from sector_pulse.storage.postgres_task_repository import PostgresTaskRepository
from sector_pulse.storage.runtime_bundle import build_postgres_storage


def test_postgres_bundle_uses_direct_repositories() -> None:
    bundle = build_postgres_storage(PostgresDatabase("postgresql://unused/unused"))

    assert isinstance(bundle.task, RuntimeTaskRepositoryPort)
    assert type(bundle.task).__name__ == "PostgresTaskRepository"
    assert isinstance(bundle.operations, OperationsQueryPort)
    assert type(bundle.operations).__name__ == "PostgresOperationsQuery"
    assert not hasattr(runtime_bundle, "BlockingAsyncRepository")


def test_postgres_runtime_repository_methods_are_synchronous() -> None:
    task_methods = (
        "create_or_get_run",
        "claim_run",
        "transition",
        "save_checkpoint",
        "get_latest_valid_checkpoint",
        "list_events",
        "record_task_event",
        "count_runs",
        "get_task_detail",
        "recover_expired_leases",
        "request_cancel",
        "recover_interrupted",
        "link_data_run",
        "list_linked_runs",
        "claim_ready_linked_run",
        "fail_claimed_run",
        "mark_content_started",
        "insert_schedule",
        "list_schedules",
        "get_schedule",
        "list_due_schedules",
        "record_schedule_trigger",
        "update_schedule_next_run",
    )
    for method in task_methods:
        assert not inspect.iscoroutinefunction(getattr(PostgresTaskRepository, method))
    assert not inspect.iscoroutinefunction(PostgresOperationsQuery.list_records)
