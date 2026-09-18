"""Programmatic, server-bound editorial submission services."""

import hashlib
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.orchestration.data_tools import require_live_task_owner
from sector_pulse.application.orchestration.editorial_context import (
    BoundEditorialContext,
    BoundRevisionContext,
)
from sector_pulse.application.research_library.evidence_access import AcceptedEvidenceIndex
from sector_pulse.application.writing.agent_validation import validate_prohibited_language
from sector_pulse.application.writing.draft_quality import (
    draft_quality_issues,
    internal_evidence_issues,
)
from sector_pulse.application.writing.revision_agent import RevisionChanges, _apply, _scope
from sector_pulse.domain.orchestration.models import ArtifactRef
from sector_pulse.domain.research_library.retrieval import AcceptedEvidenceClaim
from sector_pulse.domain.writing.article import (
    ArticleDraft,
    ArticleOutline,
    ArticleSection,
    ArticleSource,
    DraftStatus,
)
from sector_pulse.domain.writing.attribution import LEVEL_RANK
from sector_pulse.domain.writing.editorial import (
    ArticleDraftSubmission,
    ArticleOutlineSubmission,
    EditorialDraftArtifact,
    EditorialOutlineArtifact,
)
from sector_pulse.ports.orchestration import SnapshotRepository, TransactionSession
from sector_pulse.storage.ports.news import NewsEvidenceRepositoryPort
from sector_pulse.storage.ports.research_library import AcceptedEvidenceRepositoryPort
from sector_pulse.storage.ports.writing import (
    EditorialDraftRepositoryPort,
    EditorialOutlineRepositoryPort,
)


def _internal_source(claim: AcceptedEvidenceClaim) -> ArticleSource:
    """内部证据在草稿来源清单里的样子：定位得住，但不给地址。

    标题由服务端拼：模型能引用的只有它读过的句柄，而那些句柄带回来的定位就是拼标题的全部
    素材。`citation_url` 一律留空——规格 15.2 不把内部下载地址交给任何 Agent。
    """
    first = claim.claim.source_refs[0]
    locator = f"第 {first.page_start} 页" if first.page_start is not None else first.chunk_id
    return ArticleSource(
        source_id=claim.evidence_id,
        title=f"内部研究资料库 {first.document_id}（版本 {first.document_version_id}，{locator}）",
        publisher="内部研究资料库",
    )


class EditorialOutlinePersistence:
    def __init__(self, outline: EditorialOutlineArtifact) -> None:
        self.outline = outline

    def write(self, session: TransactionSession, artifact: object) -> None:
        del artifact
        outline = self.outline
        session.execute(
            "INSERT INTO editorial_outline_artifacts (outline_id, run_id, task_id, attempt, "
            "selection_version, input_fingerprint, outline_hash, payload_json, created_at) "
            "VALUES (:outline_id, :run_id, :task_id, :attempt, :selection_version, "
            ":input_fingerprint, :outline_hash, :payload_json, :created_at)",
            {
                "outline_id": str(outline.outline_id),
                "run_id": str(outline.run_id),
                "task_id": str(outline.task_id),
                "attempt": outline.attempt,
                "selection_version": outline.selection_version,
                "input_fingerprint": outline.input_fingerprint,
                "outline_hash": outline.outline_hash,
                "payload_json": outline.model_dump_json(),
                "created_at": outline.created_at.isoformat(),
            },
        )

    def exists(self, session: TransactionSession, artifact: object) -> bool:
        del artifact
        return bool(
            session.rows(
                "SELECT 1 FROM editorial_outline_artifacts WHERE outline_id=:outline_id",
                {"outline_id": str(self.outline.outline_id)},
            )
        )


class SubmitOutlineService:
    def __init__(
        self,
        *,
        orchestration: SnapshotRepository,
        committer: AtomicArtifactCommitter,
    ) -> None:
        self._orchestration = orchestration
        self._committer = committer

    def submit(
        self,
        *,
        context: BoundEditorialContext,
        submission: ArticleOutlineSubmission,
        now: datetime | None = None,
    ) -> EditorialOutlineArtifact:
        created_at = now or datetime.now(UTC)
        submission = ArticleOutlineSubmission.model_validate(submission.model_dump())
        require_live_task_owner(
            self._orchestration,
            context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
            now=created_at,
        )
        selected = set(context.selection.selected_sector_ids)
        submitted = set(submission.sector_ids)
        if not submitted <= selected:
            raise ValueError("outline contains an unconfirmed sector")
        omitted = selected - submitted
        if set(submission.excluded_sector_reasons) != omitted:
            raise ValueError("excluded sector reasons must match omitted sectors")
        if any(not value.strip() for value in submission.excluded_sector_reasons.values()):
            raise ValueError("excluded sector reasons must be non-empty")

        input_analysis_ids = tuple(item.analysis_id for item in context.analyses)
        canonical = submission.model_dump_json()
        outline_hash = hashlib.sha256(canonical.encode()).hexdigest()
        fingerprint_payload = (
            f"{context.run_id}:{context.selection.version}:"
            f"{','.join(map(str, input_analysis_ids))}:{outline_hash}"
        )
        fingerprint = hashlib.sha256(fingerprint_payload.encode()).hexdigest()
        outline_id = uuid5(NAMESPACE_URL, f"article-outline:{fingerprint}")
        outline = ArticleOutline(
            outline_id=outline_id,
            run_id=context.run_id,
            **submission.model_dump(),
        )
        result = EditorialOutlineArtifact(
            outline_id=outline_id,
            run_id=context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            selection_version=context.selection.version,
            input_analysis_ids=input_analysis_ids,
            input_fingerprint=fingerprint,
            outline_hash=outline_hash,
            outline=outline,
            created_at=created_at,
        )
        artifact = ArtifactRef(
            artifact_id=outline_id,
            task_id=context.task_id,
            attempt=context.attempt,
            kind="article_outline",
            reference=f"article-outline:{outline_id}",
        )
        self._committer.commit(
            artifact,
            worker_id=context.worker_id,
            persistence=EditorialOutlinePersistence(result),
            now=created_at,
        )
        return result


class EditorialDraftPersistence:
    def __init__(self, draft: EditorialDraftArtifact) -> None:
        self.draft = draft

    def write(self, session: TransactionSession, artifact: object) -> None:
        del artifact
        draft = self.draft
        session.execute(
            "INSERT INTO editorial_draft_artifacts (artifact_id, draft_id, run_id, task_id, "
            "attempt, version, outline_id, input_fingerprint, draft_hash, payload_json, "
            "created_at, base_draft_artifact_id, review_artifact_id, revision_round) VALUES "
            "(:artifact_id, :draft_id, :run_id, :task_id, :attempt, :version, :outline_id, "
            ":input_fingerprint, :draft_hash, :payload_json, :created_at, "
            ":base_draft_artifact_id, :review_artifact_id, :revision_round)",
            {
                "artifact_id": str(draft.artifact_id),
                "draft_id": str(draft.draft.draft_id),
                "run_id": str(draft.run_id),
                "task_id": str(draft.task_id),
                "attempt": draft.attempt,
                "version": draft.draft.version,
                "outline_id": str(draft.outline_id),
                "input_fingerprint": draft.input_fingerprint,
                "draft_hash": draft.draft_hash,
                "payload_json": draft.model_dump_json(),
                "created_at": draft.created_at.isoformat(),
                "base_draft_artifact_id": (
                    str(draft.base_draft_artifact_id)
                    if draft.base_draft_artifact_id is not None
                    else None
                ),
                "review_artifact_id": (
                    str(draft.review_artifact_id)
                    if draft.review_artifact_id is not None
                    else None
                ),
                "revision_round": draft.revision_round,
            },
        )

    def exists(self, session: TransactionSession, artifact: object) -> bool:
        del artifact
        return bool(
            session.rows(
                "SELECT 1 FROM editorial_draft_artifacts WHERE artifact_id=:artifact_id",
                {"artifact_id": str(self.draft.artifact_id)},
            )
        )


class SubmitDraftService:
    def __init__(
        self,
        *,
        orchestration: SnapshotRepository,
        committer: AtomicArtifactCommitter,
        outlines: EditorialOutlineRepositoryPort,
        news_evidence: NewsEvidenceRepositoryPort,
        accepted_evidence: AcceptedEvidenceRepositoryPort | None = None,
    ) -> None:
        self._orchestration = orchestration
        self._committer = committer
        self._outlines = outlines
        self._news_evidence = news_evidence
        # 没有内部资料库的部署就是 None：那时草稿里出现的每一个句柄都必须是新闻事件 ID，
        # 既有的来源校验照旧挡住别的。
        self._accepted_evidence = accepted_evidence

    def submit(
        self,
        *,
        context: BoundEditorialContext,
        outline_artifact_id: UUID,
        submission: ArticleDraftSubmission,
        now: datetime | None = None,
    ) -> EditorialDraftArtifact:
        created_at = now or datetime.now(UTC)
        submission = ArticleDraftSubmission.model_validate(submission.model_dump())
        require_live_task_owner(
            self._orchestration,
            context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
            now=created_at,
        )
        state = self._orchestration.load(context.run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        reference = next(
            (item for item in state.artifacts if item.artifact_id == outline_artifact_id),
            None,
        )
        if (
            reference is None
            or reference.kind != "article_outline"
            or reference.task_id != context.task_id
            or reference.attempt != context.attempt
        ):
            raise ValueError("outline artifact is not authorized")
        outline = self._outlines.get(outline_artifact_id)
        if (
            outline is None
            or outline.run_id != context.run_id
            or outline.task_id != context.task_id
            or outline.attempt != context.attempt
        ):
            raise ValueError("outline is unavailable for this context")

        sections_by_sector = {item.sector_id: item for item in submission.sections}
        if len(sections_by_sector) != len(submission.sections) or set(
            sections_by_sector
        ) != set(outline.outline.sector_ids):
            raise ValueError("draft sections must match the outline sectors")
        if len({item.section_id for item in submission.sections}) != len(
            submission.sections
        ):
            raise ValueError("draft section IDs must be unique")
        cards = {item.card.sector_id: item.card for item in context.analyses}
        allowed_event_ids = tuple(
            dict.fromkeys(
                event_id
                for sector_id in outline.outline.sector_ids
                for event_id in (
                    *cards[sector_id].supporting_evidence_ids,
                    *cards[sector_id].background_event_ids,
                )
            )
        )
        events = self._news_evidence.get_events(allowed_event_ids)
        sources: dict[str, ArticleSource] = {}
        for event in events:
            document = next(
                (item for item in event.documents if item.get("citation_url")), None
            )
            if document is not None:
                sources[event.event_id] = ArticleSource(
                    source_id=event.event_id,
                    title=document.get("title") or event.canonical_title,
                    publisher=document.get("publisher"),
                    citation_url=document.get("citation_url"),
                    published_at=document.get("published_at") or event.first_published_at,
                )

        evidence = (
            AcceptedEvidenceIndex.load(snapshot=state, repository=self._accepted_evidence)
            if self._accepted_evidence is not None
            else AcceptedEvidenceIndex()
        )
        internal_sources = {
            evidence_id: _internal_source(claim)
            for evidence_id, claim in evidence.claims.items()
        }
        sections = []
        referenced_sources: set[str] = set()
        for sector_id in outline.outline.sector_ids:
            item = sections_by_sector[sector_id]
            card = cards[sector_id]
            allowed = (
                set(card.supporting_evidence_ids) | set(card.background_event_ids)
            ) & sources.keys()
            # 内部证据与新闻事件共用一个引用位：草稿不必知道两种来源的区别，但两种都要能核对
            # 来源。版本是否仍有效不在这里挡——那是确定性检查要报的结论，报出代码比换一句
            # "引用了未经验证的来源"更有用。
            allowed = allowed | set(internal_sources)
            if not set(item.source_ids) <= allowed:
                raise ValueError("draft section references an unverified source")
            for claim in item.claims:
                if not set(claim.evidence_ids) <= set(item.source_ids) & allowed:
                    raise ValueError("draft claim references an unverified source")
                if (
                    claim.attribution_level is not None
                    and LEVEL_RANK[claim.attribution_level] > LEVEL_RANK[card.allowed_max_level]
                ):
                    raise ValueError("draft claim exceeds the attribution ceiling")
                validate_prohibited_language(claim.text)
            referenced_sources.update(item.source_ids)
            sections.append(
                ArticleSection(
                    **item.model_dump(),
                    character_count=len(item.body),
                )
            )
        for value in (
            *submission.titles,
            submission.introduction,
            submission.conclusion,
            submission.risk_notice,
            *(item.heading + "\n" + item.body for item in submission.sections),
        ):
            validate_prohibited_language(value)
        character_count = (
            len(submission.introduction)
            + len(submission.conclusion)
            + sum(len(item.body) for item in sections)
        )
        if not 1000 <= character_count <= 1800:
            raise ValueError("draft character count must be between 1000 and 1800")
        draft_id = uuid5(NAMESPACE_URL, f"article-draft:{outline.outline_id}")
        draft = ArticleDraft(
            draft_id=draft_id,
            run_id=context.run_id,
            version=1,
            status=DraftStatus.UNREVIEWED,
            titles=submission.titles,
            introduction=submission.introduction,
            sections=tuple(sections),
            conclusion=submission.conclusion,
            risk_notice=submission.risk_notice,
            sources=tuple(
                sources[item] for item in allowed_event_ids if item in referenced_sources
            )
            + tuple(
                internal_sources[item]
                for item in sorted(referenced_sources & internal_sources.keys())
            ),
            character_count=character_count,
        )
        issues = (
            *draft_quality_issues(draft, cards),
            *internal_evidence_issues(draft, cards, evidence),
        )
        if issues:
            details = "; ".join(
                f"{issue.code}[{issue.section_id or 'global'}]: {issue.message}"
                for issue in issues
            )
            raise ValueError(f"draft quality validation failed: {details}")
        canonical = draft.model_dump_json()
        draft_hash = hashlib.sha256(canonical.encode()).hexdigest()
        fingerprint = hashlib.sha256(
            f"{outline.outline_id}:{draft_hash}".encode()
        ).hexdigest()
        artifact_id = uuid5(NAMESPACE_URL, f"article-draft-artifact:{fingerprint}")
        result = EditorialDraftArtifact(
            artifact_id=artifact_id,
            run_id=context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            outline_id=outline.outline_id,
            input_fingerprint=fingerprint,
            draft_hash=draft_hash,
            draft=draft,
            created_at=created_at,
        )
        self._committer.commit(
            ArtifactRef(
                artifact_id=artifact_id,
                task_id=context.task_id,
                attempt=context.attempt,
                kind="article_draft",
                reference=f"article-draft:{artifact_id}",
            ),
            worker_id=context.worker_id,
            persistence=EditorialDraftPersistence(result),
            now=created_at,
        )
        return result


class SubmitRevisionService:
    def __init__(
        self,
        *,
        orchestration: SnapshotRepository,
        committer: AtomicArtifactCommitter,
        drafts: EditorialDraftRepositoryPort,
    ) -> None:
        self._orchestration = orchestration
        self._committer = committer
        self._drafts = drafts

    def submit(
        self,
        *,
        context: BoundRevisionContext,
        base_draft_artifact_id: UUID,
        review_artifact_id: UUID,
        changes: RevisionChanges,
        now: datetime | None = None,
    ) -> EditorialDraftArtifact:
        created_at = now or datetime.now(UTC)
        changes = RevisionChanges.model_validate(changes.model_dump())
        require_live_task_owner(
            self._orchestration,
            context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
            now=created_at,
        )
        if context.role != "A3":
            raise ValueError("revision submission requires A3")
        if (
            base_draft_artifact_id != context.draft.artifact_id
            or review_artifact_id != context.review.artifact_id
        ):
            raise ValueError("revision inputs are outside the bound context")
        if (
            context.review.draft_artifact_id != base_draft_artifact_id
            or context.review.report.draft_id != str(context.draft.draft.draft_id)
            or context.review.report.draft_version != context.draft.draft.version
            or context.review.report.decision.value != "REVISE"
        ):
            raise ValueError("review does not authorize the base draft")
        if context.draft.revision_round >= 2:
            raise ValueError("maximum revision rounds reached")
        latest = self._drafts.latest_version(context.draft.draft.draft_id)
        if latest is None or latest.artifact_id != context.draft.artifact_id:
            raise ValueError("draft base version is stale")
        state = self._orchestration.load(context.run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        for reference in state.artifacts:
            if reference.kind != "article_draft":
                continue
            stored = self._drafts.get(reference.artifact_id)
            if stored is not None and stored.review_artifact_id == review_artifact_id:
                raise ValueError("review was already used for a revision")
        cards = {item.card.sector_id: item.card for item in context.analyses}
        try:
            allowed, global_issue = _scope(context.draft.draft, context.review.report)
            revised = _apply(
                context.draft.draft,
                changes,
                allowed,
                global_issue,
                cards,
            )
        except KeyError as exc:
            raise ValueError("revision validation failed") from exc
        except ValueError as exc:
            if str(exc) == "REVISION_NO_CHANGE":
                raise ValueError("revision makes no change") from exc
            raise ValueError("revision scope or content is invalid") from exc
        if not 1000 <= revised.character_count <= 1800:
            raise ValueError("revised draft character count must be between 1000 and 1800")
        draft_hash = hashlib.sha256(revised.model_dump_json().encode()).hexdigest()
        fingerprint = hashlib.sha256(
            (
                f"{base_draft_artifact_id}:{review_artifact_id}:"
                f"{changes.model_dump_json()}:{draft_hash}"
            ).encode()
        ).hexdigest()
        artifact_id = uuid5(NAMESPACE_URL, f"article-draft-revision:{fingerprint}")
        result = EditorialDraftArtifact(
            artifact_id=artifact_id,
            run_id=context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            outline_id=context.draft.outline_id,
            base_draft_artifact_id=base_draft_artifact_id,
            review_artifact_id=review_artifact_id,
            revision_round=context.draft.revision_round + 1,
            input_fingerprint=fingerprint,
            draft_hash=draft_hash,
            draft=revised,
            created_at=created_at,
        )
        self._committer.commit(
            ArtifactRef(
                artifact_id=artifact_id,
                task_id=context.task_id,
                attempt=context.attempt,
                kind="article_draft",
                reference=f"article-draft:{artifact_id}",
            ),
            worker_id=context.worker_id,
            persistence=EditorialDraftPersistence(result),
            now=created_at,
        )
        return result


__all__ = [
    "EditorialDraftPersistence",
    "EditorialOutlinePersistence",
    "SubmitDraftService",
    "SubmitOutlineService",
    "SubmitRevisionService",
]
