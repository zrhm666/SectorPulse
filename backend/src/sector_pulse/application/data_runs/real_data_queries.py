from __future__ import annotations

import builtins
from uuid import UUID

from sector_pulse.domain.runs.real_data_run import RealDataRun
from sector_pulse.storage.ports.runs import RealDataRunRepositoryPort


class RealDataRunQueries:
    """真实数据查询只读持久化摘要，不触发 Provider。"""

    def __init__(self, repository: RealDataRunRepositoryPort) -> None:
        self._repository = repository

    def list(self, limit: int = 50) -> list[dict[str, object]]:
        return [self._serialize(run) for run in self._repository.list_runs(limit)]

    def get(self, run_id: UUID) -> dict[str, object] | None:
        run = self._repository.get_run(run_id)
        return self._serialize(run) if run else None

    def candidates(self, run_id: UUID) -> builtins.list[dict[str, object]]:
        return [item.model_dump(mode="json") for item in self._repository.get_candidates(run_id)]

    @staticmethod
    def _serialize(run: RealDataRun) -> dict[str, object]:
        payload = run.model_dump(mode="json")
        request = payload["request"]
        quality = payload["quality"]
        return {
            "run_id": payload["run_id"],
            "retry_of_run_id": payload["retry_of_run_id"],
            "provider": payload["provider"],
            "mode": request["mode"],
            "status": payload["status"],
            "requested_at": request["requested_at"],
            "cutoff_at": payload["cutoff_at"],
            "request": request,
            "quality": {**quality["market_quality"], **quality["news_quality"]},
            "quality_summary": quality,
            "downgrade_reasons": quality["downgrade_reasons"],
            "error_code": payload["error_code"],
            "finished_at": payload["finished_at"],
        }
