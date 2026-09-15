"""Human draft edits that share one concurrency guard with the agent.

A human patch writes `article_drafts`; an agent revision admits an editorial
draft artifact. They touch different tables, so neither transaction can see the
other move by looking at the draft version alone. The orchestration snapshot
revision is the one counter both can advance, so a human edit states the
revision it read and commits the draft change in that revision's transaction:
either both land or neither does.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sector_pulse.domain.review.editing import DraftPatch
from sector_pulse.domain.writing.article import ArticleDraft
from sector_pulse.ports.orchestration import SnapshotRepository
from sector_pulse.storage.ports.review import DraftEditRepositoryPort

REVISION_EVENT = "draft.patched"


class HumanDraftEditService:
    def __init__(
        self,
        *,
        draft_edits: DraftEditRepositoryPort,
        orchestration: SnapshotRepository,
    ) -> None:
        self._draft_edits = draft_edits
        self._orchestration = orchestration

    def apply(
        self,
        run_id: UUID,
        draft_id: UUID,
        base_version: int,
        operations: tuple[DraftPatch, ...],
        *,
        actor: str,
        base_revision: int | None,
    ) -> ArticleDraft:
        """Apply one human edit, refusing when the agent moved first.

        `base_revision` is the snapshot revision the editor read. Passing None
        keeps the original single-store behaviour, which is what runs without an
        orchestration snapshot (every legacy run) still need.
        """
        if base_revision is None:
            return self._draft_edits.apply_patch(
                draft_id, base_version, operations, actor=actor
            )
        state = self._orchestration.load(run_id)
        if state is None:
            return self._draft_edits.apply_patch(
                draft_id, base_version, operations, actor=actor
            )

        edited: list[ArticleDraft] = []

        def write(session: Any) -> None:
            edited.append(
                self._draft_edits.apply_patch_in_transaction(
                    session.connection, draft_id, base_version, operations, actor=actor
                )
            )

        # Building the snapshot at exactly base_revision + 1 is what makes
        # save_atomic's CAS fail loudly if the agent advanced the run meanwhile.
        claimed = state.model_copy(update={"revision": base_revision + 1})
        self._orchestration.save_atomic(claimed, base_revision, REVISION_EVENT, write)
        return edited[0]
