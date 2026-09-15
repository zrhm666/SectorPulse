"""Project orchestration snapshots into the operations run vocabulary.

Old runs live in `phase1b_runs`/`real_data_runs`; new runs live only in the
orchestration snapshot. Operations statistics must count both without
inventing the values the new engine genuinely does not record.
"""

from collections.abc import Iterable

from sector_pulse.application.operations.operations_summary import OperationalRun
from sector_pulse.domain.orchestration.models import RunSnapshot

MULTI_AGENT_MODE_LABEL = "多 Agent 分析"


def project_multi_agent_run(snapshot: RunSnapshot) -> OperationalRun | None:
    """Return the operations view of one orchestration snapshot.

    The status keeps its recorded spelling. `elapsed_ms` stays unknown because
    the snapshot records no wall-clock duration, and the total stays unknown
    while any call in the ledger is still unpriced or unsettled.
    """
    root = next((task for task in snapshot.tasks if task.parent_id is None), None)
    if root is None:
        return None
    return OperationalRun(
        run_id=str(snapshot.run_id),
        kind="content",
        mode=MULTI_AGENT_MODE_LABEL,
        status=root.status.value.upper(),
        provider=snapshot.provider,
        requested_at=snapshot.requested_at,
        finished_at=snapshot.finished_at,
        elapsed_ms=None,
        total_cost_cny=(
            None if snapshot.ledger.has_unknown_cost else snapshot.ledger.charged_cny
        ),
        candidate_count=len({task.scope for task in snapshot.tasks if task.role == "A2"}),
        execution_engine="multi_agent",
    )


def project_multi_agent_runs(snapshots: Iterable[RunSnapshot]) -> list[OperationalRun]:
    return [run for snapshot in snapshots if (run := project_multi_agent_run(snapshot))]
