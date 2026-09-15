import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from backend.tests.integration.test_orchestration_editorial_context import (
    build_editorial_context,
)


def build_context_and_outline(tmp_path):
    from sector_pulse.application.orchestration.editorial_context import (
        BoundEditorialContextReader,
    )
    from sector_pulse.application.orchestration.editorial_tools import SubmitOutlineService
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
    from sector_pulse.domain.writing.editorial import ArticleOutlineSubmission

    repository, snapshot, writer, selections, analyses, _ = build_editorial_context(tmp_path)
    context = BoundEditorialContextReader(
        orchestration=repository,
        selections=selections,
        analyses=analyses,
        run_id=snapshot.run_id,
    ).read(task_id=writer.task_id, attempt=1, worker_id="writer-worker")

    class Committer:
        def commit(self, artifact, **kwargs):
            TaskCoordinator(repository, snapshot.run_id).submit_artifact(
                artifact,
                worker_id=kwargs["worker_id"],
            )
            return artifact

    outline = SubmitOutlineService(
        orchestration=repository,
        committer=Committer(),
    ).submit(
        context=context,
        submission=ArticleOutlineSubmission(
            sector_ids=("sector-1", "sector-2", "sector-3"),
            order_reasons={
                "sector-1": "一",
                "sector-2": "二",
                "sector-3": "三",
            },
            title_directions=("方向",),
            thesis="审慎观察",
            section_character_budgets={
                "sector-1": 360,
                "sector-2": 360,
                "sector-3": 360,
            },
            excluded_sector_reasons={},
        ),
    )
    return repository, context, outline


def valid_submission():
    from sector_pulse.domain.writing.editorial import (
        ArticleDraftSubmission,
        ArticleSectionSubmission,
    )

    sections = tuple(
        ArticleSectionSubmission(
            section_id=f"section-{index}",
            sector_id=f"sector-{index}",
            heading=f"板块{index}：证据边界内观察",
            body=f"板块{index}的市场表现需要结合已核验信息观察。" + "审慎观察" * 85,
            claims=(),
            source_ids=(f"event-{index}",),
        )
        for index in range(1, 4)
    )
    return ArticleDraftSubmission(
        titles=("今日三个板块的证据观察",),
        introduction="本文仅梳理已确认板块和可核验事实。",
        sections=sections,
        conclusion="现有证据支持有限，后续信息仍需继续核验。",
        risk_notice="市场波动较大，本文不构成投资建议。",
    )


class FixtureEvent:
    def __init__(self, index):
        self.event_id = f"event-{index}"
        self.canonical_title = f"来源{index}"
        self.first_published_at = "2026-09-14T00:00:00+00:00"
        self.documents = (
            {
                "title": f"原文{index}",
                "publisher": "测试来源",
                "citation_url": f"https://example.test/{index}",
                "published_at": self.first_published_at,
            },
        )


class FixtureNewsEvidence:
    def get_events(self, event_ids):
        return tuple(FixtureEvent(int(item.rsplit("-", 1)[1])) for item in event_ids)


def test_t11_submit_draft_rebuilds_identity_version_counts_and_verified_sources(tmp_path):
    from sector_pulse.application.orchestration.editorial_tools import SubmitDraftService
    from sector_pulse.domain.writing.article import DraftStatus

    repository, context, outline = build_context_and_outline(tmp_path)

    class Outlines:
        def get(self, identity):
            return outline if identity == outline.outline_id else None

    class Committer:
        committed = []

        def commit(self, artifact, **kwargs):
            self.committed.append((artifact, kwargs))
            return artifact

    service = SubmitDraftService(
        orchestration=repository,
        committer=Committer(),
        outlines=Outlines(),
        news_evidence=FixtureNewsEvidence(),
    )
    result = service.submit(
        context=context,
        outline_artifact_id=outline.outline_id,
        submission=valid_submission(),
        now=datetime.now(UTC),
    )

    assert result.draft.run_id == context.run_id
    assert result.draft.version == 1
    assert result.draft.status is DraftStatus.UNREVIEWED
    assert result.draft.character_count == (
        len(result.draft.introduction)
        + len(result.draft.conclusion)
        + sum(len(item.body) for item in result.draft.sections)
    )
    assert {item.source_id for item in result.draft.sources} == {
        "event-1",
        "event-2",
        "event-3",
    }
    assert all(
        section.character_count == len(section.body) for section in result.draft.sections
    )

    from sector_pulse.domain.writing.editorial import ArticleDraftSubmission

    invalid = valid_submission().model_dump(mode="json")
    invalid["sections"][0]["heading"] = "异动观察"
    invalid["sections"][0]["body"] = "该方向仍需观察。" + "审慎观察" * 85
    with pytest.raises(ValueError, match="SECTOR_SUBJECT_MISSING"):
        service.submit(
            context=context,
            outline_artifact_id=outline.outline_id,
            submission=ArticleDraftSubmission.model_validate(invalid),
        )


def test_t11_rejects_unknown_source_wrong_sector_and_model_owned_fields(tmp_path):
    from pydantic import ValidationError
    from sector_pulse.application.orchestration.editorial_tools import SubmitDraftService

    repository, context, outline = build_context_and_outline(tmp_path)

    class Outlines:
        def get(self, identity):
            return outline

    class NewsEvidence:
        def get_events(self, event_ids):
            return ()

    class Committer:
        def commit(self, artifact, **kwargs):
            raise AssertionError("invalid draft must not be committed")

    service = SubmitDraftService(
        orchestration=repository,
        committer=Committer(),
        outlines=Outlines(),
        news_evidence=NewsEvidence(),
    )
    with pytest.raises(ValueError, match="verified source"):
        service.submit(
            context=context,
            outline_artifact_id=outline.outline_id,
            submission=valid_submission(),
        )
    payload = valid_submission().model_dump(mode="json")
    payload["run_id"] = str(context.run_id)
    payload["version"] = 99
    payload["status"] = "READY_FOR_HUMAN_REVIEW"
    with pytest.raises(ValidationError):
        type(valid_submission()).model_validate(payload)


@pytest.mark.asyncio
async def test_t11_tool_persists_sqlite_draft_and_replays_exact_artifact(tmp_path):
    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
    from sector_pulse.application.orchestration.editorial_context import (
        BoundEditorialContextReader,
    )
    from sector_pulse.application.orchestration.editorial_tools import (
        SubmitDraftService,
        SubmitOutlineService,
    )
    from sector_pulse.domain.writing.editorial import ArticleOutlineSubmission
    from sector_pulse.infrastructure.agents.editorial_tools import SubmitDraftTool
    from sector_pulse.storage.sqlite.writing.editorial_repository import (
        SQLiteEditorialDraftRepository,
        SQLiteEditorialOutlineRepository,
    )

    repository, snapshot, writer, selections, analyses, _ = build_editorial_context(tmp_path)
    with repository.database.transaction() as connection:
        connection.execute(
            "INSERT INTO analysis_runs (run_id, mode, requested_at) VALUES (?, 'LIVE', ?)",
            (str(snapshot.run_id), datetime.now(UTC).isoformat()),
        )
    context = BoundEditorialContextReader(
        orchestration=repository,
        selections=selections,
        analyses=analyses,
        run_id=snapshot.run_id,
    ).read(task_id=writer.task_id, attempt=1, worker_id="writer-worker")
    committer = AtomicArtifactCommitter(repository, snapshot.run_id)
    outline = SubmitOutlineService(
        orchestration=repository,
        committer=committer,
    ).submit(
        context=context,
        submission=ArticleOutlineSubmission(
            sector_ids=context.selection.selected_sector_ids,
            order_reasons={item: item for item in context.selection.selected_sector_ids},
            title_directions=("方向",),
            thesis="审慎观察",
            section_character_budgets={
                item: 360 for item in context.selection.selected_sector_ids
            },
            excluded_sector_reasons={},
        ),
    )
    drafts = SQLiteEditorialDraftRepository(repository.database)
    tool = SubmitDraftTool(
        SubmitDraftService(
            orchestration=repository,
            committer=committer,
            outlines=SQLiteEditorialOutlineRepository(repository.database),
            news_evidence=FixtureNewsEvidence(),
        ),
        drafts=drafts,
        context=context,
    )
    assert set(tool.parameters["properties"]) == {
        "outline_artifact_id",
        "submission",
    }
    result = await tool.run(
        outline_artifact_id=str(outline.outline_id),
        submission=valid_submission().model_dump(mode="json"),
    )
    assert result.success
    artifact_id = json.loads(result.content)["artifact_refs"][0]
    persisted = drafts.get(UUID(artifact_id))
    assert persisted is not None
    assert persisted.draft.version == 1
    assert drafts.get_version(persisted.draft.draft_id, 1) == persisted
    assert tool.replay(result.metadata["result_reference"]).content == result.content
    rejected = await tool.run(
        outline_artifact_id=str(outline.outline_id),
        submission=valid_submission().model_dump(mode="json"),
        status="READY_FOR_HUMAN_REVIEW",
    )
    assert not rejected.success

    invalid_submission = valid_submission().model_dump(mode="json")
    invalid_submission["sections"][0]["source_ids"] = ["event-unknown"]
    semantic_rejection = await tool.run(
        outline_artifact_id=str(outline.outline_id),
        submission=invalid_submission,
    )
    assert not semantic_rejection.success
    assert "unverified source" in semantic_rejection.content
