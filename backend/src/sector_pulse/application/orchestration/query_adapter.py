"""Read-only Web DTO adapter for orchestration snapshots."""

from typing import Any
from uuid import UUID

from sector_pulse.domain.orchestration.models import ArtifactRef, RunSnapshot, TaskStatus
from sector_pulse.web.schemas.runs import RunDetail, RunSummary


class MultiAgentRunQueryAdapter:
    def __init__(
        self,
        repository: Any,
        storage: Any | None = None,
        *,
        legacy: Any | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._legacy = legacy

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        current: list[RunSummary] = [
            detail
            for snapshot in self._repository.list_snapshots(limit)
            if (detail := self.get_run(snapshot.run_id)) is not None
        ]
        if self._legacy is None or len(current) >= limit:
            return current[:limit]
        current_ids = {item.run_id for item in current}
        historical = [
            item
            for item in self._legacy.list_runs(limit)
            if item.run_id not in current_ids
        ]
        return [*current, *historical][:limit]

    def get_run(self, run_id: UUID) -> RunDetail | None:
        snapshot = self._repository.load(run_id)
        if snapshot is None:
            return self._legacy.get_run(run_id) if self._legacy is not None else None
        root = next((task for task in snapshot.tasks if task.parent_id is None), None)
        if root is None:
            return None
        draft = self.latest_draft(run_id) if self._storage is not None else None
        review = self.get_review(run_id) if self._storage is not None else None
        sector_count = (
            len(draft.sections)
            if draft is not None
            else len({task.scope for task in snapshot.tasks if task.role == "A2"})
        )
        return RunDetail(
            run_id=run_id,
            execution_engine="multi_agent",
            requested_at=snapshot.requested_at,
            provider=snapshot.provider,
            status=root.status.value.upper(),
            elapsed_ms=None,
            total_cost_cny=(
                None
                if snapshot.ledger.has_unknown_cost
                else str(snapshot.ledger.charged_cny)
            ),
            draft_id=draft.draft_id if draft is not None else None,
            retry_of_run_id=snapshot.retry_of_run_id,
            input_json_hash=None,
            error_message=root.public_error_code,
            sector_count=sector_count,
            review_decision=review["decision"] if review is not None else None,
            retryable=root.status in {TaskStatus.FAILED, TaskStatus.INTERRUPTED},
        )

    def get_radar(self, run_id: UUID) -> dict[str, Any]:
        snapshot = self._repository.load(run_id)
        if snapshot is None or self._storage is None:
            return {"cards": []}
        cards = []
        for artifact in snapshot.artifacts:
            if artifact.kind != "sector_analysis":
                continue
            analysis = self._storage.sector_analyses.get(artifact.artifact_id)
            if analysis is not None:
                cards.append(analysis.card.model_dump(mode="json"))
        return {"cards": cards}

    def get_draft(self, run_id: UUID) -> dict[str, Any]:
        """Return the draft versions plus the revision a human edit must state.

        `revision` is the value an editor has to send back as `base_revision` so
        that its write shares the agent's concurrency guard; it is None for a run
        whose draft is not governed by a snapshot.
        """
        snapshot = self._repository.load(run_id)
        if snapshot is None or self._storage is None:
            return {"versions": [], "revision": None}
        edited = self._legacy_edited_draft(run_id)
        if edited is not None:
            return {"versions": [edited.model_dump(mode="json")], "revision": snapshot.revision}
        versions = []
        for artifact in snapshot.artifacts:
            if artifact.kind != "article_draft":
                continue
            draft = self._storage.editorial_drafts.get(artifact.artifact_id)
            if draft is not None:
                versions.append(draft.draft.model_dump(mode="json"))
        return {"versions": versions, "revision": snapshot.revision}

    def latest_draft(self, run_id: UUID) -> Any | None:
        """Return the latest persisted editorial draft for human read-only checks."""
        snapshot = self._repository.load(run_id)
        if snapshot is None or self._storage is None:
            return None
        edited = self._legacy_edited_draft(run_id)
        if edited is not None:
            return edited
        drafts = []
        for artifact in snapshot.artifacts:
            if artifact.kind != "article_draft":
                continue
            candidate = self._storage.editorial_drafts.get(artifact.artifact_id)
            if candidate is not None:
                drafts.append(candidate.draft)
        return max(drafts, key=lambda item: item.version, default=None)

    def _legacy_edited_draft(self, run_id: UUID) -> Any | None:
        draft_edits = getattr(self._storage, "draft_edit", None)
        if draft_edits is None:
            return None
        try:
            return draft_edits.latest_for_run(run_id)
        except KeyError:
            return None

    def get_evidence(self, run_id: UUID) -> dict[str, Any]:
        del run_id
        return {"sectors": [], "events": [], "invocations": []}

    @staticmethod
    def _no_review() -> dict[str, Any]:
        """A run with nothing recorded, never a stand-in for "no problems"."""
        return {
            "decision": None,
            "revision_round": None,
            "issues": [],
            "draft_id": None,
            "draft_version": None,
        }

    def get_review(self, run_id: UUID) -> dict[str, Any]:
        snapshot = self._repository.load(run_id)
        if snapshot is None or self._storage is None:
            return self._no_review()
        pairs = [
            (artifact, self._storage.independent_reviews.get(artifact.artifact_id))
            for artifact in snapshot.artifacts
            if artifact.kind == "independent_review"
        ]
        found = next(
            ((ref, loaded) for ref, loaded in reversed(pairs) if loaded is not None), None
        )
        if found is None:
            return self._no_review()
        reviewed, review = found
        draft_id, version = self._reviewed_draft(snapshot, reviewed)
        return {
            "decision": review.report.decision.value,
            "revision_round": review.report.revision_round,
            "issues": [item.model_dump(mode="json") for item in review.report.issues],
            "draft_id": str(draft_id) if draft_id is not None else None,
            "draft_version": version,
        }

    def _reviewed_draft(
        self, snapshot: RunSnapshot, review_ref: ArtifactRef
    ) -> tuple[Any, int | None]:
        """Return the draft the review was written against, not the run's current one.

        A4 consumes one explicit, version-pinned draft artifact. A human edit
        afterwards creates a higher version on purpose, so the review must stay
        bound to the version it actually read.
        """
        author = next(
            (task for task in snapshot.tasks if task.task_id == review_ref.task_id), None
        )
        if author is None or self._storage is None:
            return None, None
        artifacts_by_id = {item.artifact_id: item for item in snapshot.artifacts}
        for identity in author.input_artifact_ids:
            draft_ref = artifacts_by_id.get(identity)
            if draft_ref is None or draft_ref.kind != "article_draft":
                continue
            stored = self._storage.editorial_drafts.get(draft_ref.artifact_id)
            if stored is not None:
                return stored.draft.draft_id, stored.draft.version
        return None, None

    def get_agent_trace(self, run_id: UUID) -> dict[str, Any]:
        snapshot = self._repository.load(run_id)
        if snapshot is None:
            return {
                "tasks": [],
                "artifacts": [],
                "tool_invocations": [],
                "model_calls": [],
                "budget": {},
            }
        tasks = [
            {
                "task_id": str(task.task_id),
                "parent_id": str(task.parent_id) if task.parent_id is not None else None,
                "role": task.role,
                "scope": task.scope,
                "attempt": task.attempt,
                "status": task.status.value,
                "worker_id": task.worker_id,
                "lease_expires_at": (
                    task.lease_expires_at.isoformat() if task.lease_expires_at is not None else None
                ),
                "public_error_code": task.public_error_code,
                "selection_version": task.selection_version,
            }
            for task in snapshot.tasks
        ]
        return {
            "tasks": tasks,
            "artifacts": [artifact.model_dump(mode="json") for artifact in snapshot.artifacts],
            "tool_invocations": [
                invocation.model_dump(mode="json")
                for invocation in snapshot.ledger.tool_invocations
            ],
            "model_calls": [
                reservation.model_dump(mode="json")
                for reservation in snapshot.ledger.reservations
            ],
            "budget": {
                "calls": snapshot.ledger.calls,
                "tool_calls": snapshot.ledger.tool_calls,
                "charged_tokens": snapshot.ledger.charged_tokens,
                "charged_cny": str(snapshot.ledger.charged_cny),
                "has_unknown_cost": snapshot.ledger.has_unknown_cost,
            },
        }

    def render_draft_markdown(self, run_id: UUID) -> str | None:
        draft = self._latest_ready_draft(run_id)
        if draft is None:
            return None
        from decimal import Decimal

        from sector_pulse.application.writing.phase1b_pipeline import Phase1BRunResult
        from sector_pulse.domain.llm import MoneyCny
        from sector_pulse.reporting.phase1b_report import render_phase1b_markdown

        return render_phase1b_markdown(
            Phase1BRunResult(
                status="READY_FOR_HUMAN_REVIEW",
                analysis_cards=(),
                outline=None,
                draft=draft,
                review=None,
                total_cost_cny=MoneyCny(amount=Decimal("0")),
                elapsed_ms=0,
            )
        )

    def render_draft_text(self, run_id: UUID) -> str | None:
        draft = self._latest_ready_draft(run_id)
        if draft is None:
            return None
        from decimal import Decimal

        from sector_pulse.application.writing.phase1b_pipeline import Phase1BRunResult
        from sector_pulse.domain.llm import MoneyCny
        from sector_pulse.reporting.phase1b_report import render_phase1b_text

        return render_phase1b_text(
            Phase1BRunResult(
                status="READY_FOR_HUMAN_REVIEW",
                analysis_cards=(),
                outline=None,
                draft=draft,
                review=None,
                total_cost_cny=MoneyCny(amount=Decimal("0")),
                elapsed_ms=0,
            )
        )

    def _latest_ready_draft(self, run_id: UUID) -> Any | None:
        draft = self.latest_draft(run_id)
        if draft is None or draft.status.value != "READY_FOR_HUMAN_REVIEW":
            return None
        return draft
