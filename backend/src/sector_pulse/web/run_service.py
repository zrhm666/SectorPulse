# backend/src/sector_pulse/web/run_service.py
import asyncio
import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from sector_pulse.application.phase1b_pipeline import (
    Phase1BDependencies,
    Phase1BRequest,
    run_phase1b_pipeline,
)
from sector_pulse.application.progress import ProgressSink
from sector_pulse.application.task_registry import RunTaskRegistry
from sector_pulse.config.llm_config import LLMRuntimeConfig
from sector_pulse.domain.article import ArticleDraft, ArticleSource, DraftStatus
from sector_pulse.domain.llm import AgentInvocation
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.storage.phase1b_runs_repository import (
    Phase1BRunRow,
)
from sector_pulse.storage.ports import (
    AgentInvocationRepositoryPort,
    NewsEvidenceRepositoryPort,
    Phase1BRepositoryPort,
    Phase1BRunsRepositoryPort,
)
from sector_pulse.web.progress_bus import ProgressBus
from sector_pulse.web.schemas import RunDetail, RunSummary


class ProviderUnavailable(ValueError):
    pass


class RunService:
    def __init__(
        self,
        runs_repo: Phase1BRunsRepositoryPort,
        phase1b_repo: Phase1BRepositoryPort,
        invocation_repo: AgentInvocationRepositoryPort,
        news_evidence: NewsEvidenceRepositoryPort,
        prompts: PromptRegistry,
        config: LLMRuntimeConfig,
        bus: ProgressBus,
        fixture_responses: dict[str, object],
        llm_factory: dict[str, Any],
    ) -> None:
        self._runs_repo = runs_repo
        self._phase1b_repo = phase1b_repo
        self._invocation_repo = invocation_repo
        self._news_evidence = news_evidence
        self._prompts = prompts
        self._config = config
        self._bus = bus
        self._fixture_responses = fixture_responses
        self._llm_factory = llm_factory
        self._tasks = RunTaskRegistry()

    def create_run(
        self, input_json: dict[str, Any], provider: str, run_id: UUID | None = None,
        *, retry_of_run_id: UUID | None = None,
    ) -> UUID:
        # 先做同步预检，避免未配置 Live 任务先落库为 RUNNING。
        self._preflight(provider)
        run_id = run_id or uuid4()
        existing = self._runs_repo.get_run(run_id)
        if existing is not None:
            if existing.status == "RUNNING":
                return run_id
            if existing.draft_id is not None:
                return run_id
            raise ProviderUnavailable("run already has a terminal Phase 1B execution")
        request = Phase1BRequest.model_validate({"run_id": str(run_id), **input_json})
        if provider == "live":
            request = request.model_copy(
                update={"verified_sources_by_sector": self._load_verified_sources(request)}
            )
        # 输入里的 contexts/gates 可能携带其它 run_id，统一归一到本次生成的 run_id，
        # 保证 attribution 落库与后续按 run_id 读取（雷达/证据）保持一致。
        request = request.model_copy(
            update={
                "run_id": run_id,
                "contexts": tuple(
                    context.model_copy(update={"run_id": run_id}) for context in request.contexts
                ),
                "gates": {
                    sector_id: gate.model_copy(update={"run_id": run_id})
                    for sector_id, gate in request.gates.items()
                },
            }
        )
        input_hash = hashlib.sha256(
            json.dumps(input_json, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self._runs_repo.insert(
            Phase1BRunRow(
                run_id=run_id,
                requested_at=request.requested_at,
                provider=provider,
                status="RUNNING",
                input_json_hash=input_hash,
                input_json=input_json,
                retry_of_run_id=retry_of_run_id,
            )
        )

        class BridgeSink:
            def __init__(self, bus: ProgressBus, rid: UUID) -> None:
                self.bus = bus
                self.rid = rid

            def emit(self, stage: str, detail: dict[str, Any]) -> None:
                self.bus.emit(self.rid, {"type": "progress", "stage": stage, "detail": detail})

        bridge = BridgeSink(self._bus, run_id)
        self._tasks.start(run_id, self._execute(run_id, request, provider, bridge))
        return run_id

    def _load_verified_sources(
        self, request: Phase1BRequest
    ) -> dict[str, tuple[ArticleSource, ...]]:
        """从已持久化新闻元数据构建可审计来源，不把来源生成权交给模型。"""
        result: dict[str, tuple[ArticleSource, ...]] = {}
        for context in request.contexts:
            event_ids = tuple(
                dict.fromkeys(
                    context.eligible_event_ids + context.background_event_ids + context.event_ids
                )
            )
            events = self._news_evidence.get_events(event_ids)
            sources: list[ArticleSource] = []
            for event in events[:5]:
                document = next(
                    (item for item in event.documents if item.get("citation_url")),
                    None,
                )
                if document is None:
                    continue
                sources.append(
                    ArticleSource(
                        source_id=event.event_id,
                        title=document.get("title") or event.canonical_title,
                        publisher=document.get("publisher"),
                        citation_url=document.get("citation_url"),
                        published_at=document.get("published_at") or event.first_published_at,
                    )
                )
            result[context.sector_id] = tuple(sources)
        return result

    async def _execute(
        self,
        run_id: UUID,
        request: Phase1BRequest,
        provider: str,
        progress_sink: ProgressSink,
    ) -> None:
        invocations: list[AgentInvocation] = []

        def record(invocation: AgentInvocation) -> None:
            invocations.append(invocation)

        try:
            llm = self._build_llm(provider, request.run_id)
            deps = Phase1BDependencies(
                llm=llm,
                prompts=self._prompts,
                repository=self._phase1b_repo,
                invocation_repository=self._invocation_repo,
                config=self._runtime_config(provider),
            )
            result = await run_phase1b_pipeline(
                deps,
                request,
                progress_sink=progress_sink,
                invocation_sink=record,
            )
            self._runs_repo.update_status(
                run_id,
                status=result.status,
                elapsed_ms=result.elapsed_ms,
                total_cost_cny=str(result.total_cost_cny.amount),
                draft_id=result.draft.draft_id if result.draft else None,
                finished_at=datetime.now(UTC),
            )
            self._bus.emit(run_id, {"type": "done", "status": result.status})
        except asyncio.CancelledError:
            self._runs_repo.update_status(run_id, status="CANCELLED", finished_at=datetime.now(UTC))
            self._bus.emit(run_id, {"type": "cancelled"})
        except ProviderUnavailable as exc:
            self._runs_repo.update_status(
                run_id, status="FAILED", error_message=str(exc), finished_at=datetime.now(UTC)
            )
            self._bus.emit(run_id, {"type": "error", "message": str(exc)})
        except Exception as exc:
            self._runs_repo.update_status(
                run_id, status="FAILED", error_message=str(exc), finished_at=datetime.now(UTC)
            )
            self._bus.emit(run_id, {"type": "error", "message": str(exc)})
        finally:
            if invocations:
                self._invocation_repo.save(invocations)
            self._bus.close(run_id)

    @staticmethod
    def _rebind_run_id(node: Any, run_id: UUID) -> Any:
        """深度拷贝 fixture，并为每次运行生成独立且内部一致的产物标识。"""
        if isinstance(node, dict):
            return {
                key: (
                    str(run_id)
                    if key == "run_id"
                    else str(uuid5(run_id, f"{key}:{value}"))
                    if key in {"draft_id", "outline_id", "review_id"}
                    else RunService._rebind_run_id(value, run_id)
                )
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [RunService._rebind_run_id(item, run_id) for item in node]
        return node

    def _preflight(self, provider: str) -> None:
        """在创建运行前检查 Provider；不触网、不写库。"""
        if provider == "fixture":
            return
        if provider == "live":
            from sector_pulse.web.live_provider import check_live_consent, get_live_config

            if not check_live_consent():
                raise ProviderUnavailable("缺少 .live-llm-consent，真实模型被禁用")
            live_config = get_live_config()
            if live_config is None:
                raise ProviderUnavailable(
                    "缺少 SECTOR_PULSE_LLM_API_KEY / BASE_URL / MODEL 环境变量"
                )
            return
        if provider not in self._llm_factory:
            raise ProviderUnavailable(f"unknown provider: {provider}")

    def _runtime_config(self, provider: str) -> LLMRuntimeConfig:
        """Live 使用环境变量模型覆盖各阶段路由，Fixture 保持配置文件路由。"""
        if provider != "live":
            return self._config
        from sector_pulse.web.live_provider import get_live_config

        live_config = get_live_config()
        if live_config is None:
            raise ProviderUnavailable("Live Provider 配置不完整")
        model = live_config[2]
        routes = {
            stage: route.model_copy(update={"provider": "live", "model": model})
            for stage, route in self._config.routes.items()
        }
        return self._config.model_copy(update={"routes": routes})

    def _build_llm(self, provider: str, run_id: UUID) -> Any:
        if provider == "fixture":
            from sector_pulse.infrastructure.llm.fixture_provider import FixtureLLMProvider

            return FixtureLLMProvider(self._rebind_run_id(self._fixture_responses, run_id))
        if provider == "live":
            from sector_pulse.web.live_provider import (
                build_live_provider,
                check_live_consent,
                get_live_config,
            )

            if not check_live_consent():
                raise ProviderUnavailable("缺少 .live-llm-consent，真实模型被禁用")
            config_value = get_live_config()
            if config_value is None:
                raise ProviderUnavailable(
                    "缺少 SECTOR_PULSE_LLM_API_KEY / BASE_URL / MODEL 环境变量"
                )
            base_url, api_key, _model = config_value
            timeout_seconds = float(os.environ.get("SECTOR_PULSE_LLM_TIMEOUT_SECONDS", "60"))
            return build_live_provider(
                base_url,
                api_key,
                self._config.pricing,
                timeout_seconds=timeout_seconds,
            )
        factory = self._llm_factory.get(provider)
        if factory is None:
            raise ProviderUnavailable(f"unknown provider: {provider}")
        return factory()

    def retry_run(self, run_id: UUID) -> UUID:
        # 只允许对已结束且保存了输入快照的运行重试，避免重复执行 RUNNING 任务。
        row = self._runs_repo.get_run(run_id)
        if row is None or row.status in {"RUNNING"} or row.input_json is None:
            raise ProviderUnavailable("run cannot be retried without a completed input snapshot")
        return self.create_run(row.input_json, row.provider, retry_of_run_id=row.run_id)

    def cancel_run(self, run_id: UUID) -> bool:
        if not self._tasks.cancel(run_id):
            return False
        self._runs_repo.update_status(run_id, status="CANCELLED", finished_at=datetime.now(UTC))
        return True

    async def wait(self, run_id: UUID) -> None:
        await self._tasks.wait(run_id)

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        return [
            RunSummary(
                run_id=r.run_id,
                requested_at=r.requested_at,
                provider=r.provider,
                status=r.status,
                elapsed_ms=r.elapsed_ms,
                total_cost_cny=r.total_cost_cny,
                draft_id=r.draft_id,
                retry_of_run_id=r.retry_of_run_id,
            )
            for r in self._runs_repo.list_runs(limit)
        ]

    def get_run(self, run_id: UUID) -> RunDetail | None:
        row = self._runs_repo.get_run(run_id)
        if row is None:
            return None
        cards = self._phase1b_repo.get_cards(run_id)
        review = self._phase1b_repo.get_review(run_id)
        return RunDetail(
            run_id=row.run_id,
            requested_at=row.requested_at,
            provider=row.provider,
            status=row.status,
            elapsed_ms=row.elapsed_ms,
            total_cost_cny=row.total_cost_cny,
            draft_id=row.draft_id,
            retry_of_run_id=row.retry_of_run_id,
            input_json_hash=row.input_json_hash,
            error_message=row.error_message,
            sector_count=len(cards),
            review_decision=review.decision.value if review else None,
            retryable=row.status != "RUNNING" and row.input_json is not None,
        )

    def get_radar(self, run_id: UUID) -> dict[str, Any]:
        cards = self._phase1b_repo.get_cards(run_id)
        gates = self._phase1b_repo.get_gates(run_id)
        gate_by_sector = {g.sector_id: g for g in gates}
        return {
            "cards": [
                {
                    "sector_id": c.sector_id,
                    "sector_kind": c.sector_kind.value,
                    "attribution_level": c.attribution_level.value,
                    "allowed_max_level": c.allowed_max_level.value,
                    "confidence": str(c.confidence),
                    "conclusion": c.conclusion,
                    "supporting_evidence_ids": list(c.supporting_evidence_ids),
                    "counter_evidence": list(c.counter_evidence),
                    "uncertainties": list(c.uncertainties),
                    "forbidden_inferences": list(c.forbidden_inferences),
                    "claims": [claim.model_dump(mode="json") for claim in c.claims],
                    "gate_reasons": list(
                        gate_by_sector[c.sector_id].reasons if c.sector_id in gate_by_sector else ()
                    ),
                }
                for c in cards
            ]
        }

    def get_draft(self, run_id: UUID) -> dict[str, Any]:
        drafts = self._phase1b_repo.get_drafts(run_id)
        return {
            "versions": [
                {
                    "version": d.version,
                    "status": d.status.value,
                    "titles": list(d.titles),
                    "introduction": d.introduction,
                    "sections": [s.model_dump(mode="json") for s in d.sections],
                    "conclusion": d.conclusion,
                    "risk_notice": d.risk_notice,
                    "sources": [s.model_dump(mode="json") for s in d.sources],
                    "character_count": d.character_count,
                }
                for d in drafts
            ]
        }

    def get_evidence(self, run_id: UUID) -> dict[str, Any]:
        contexts = self._phase1b_repo.get_contexts(run_id)
        cards = self._phase1b_repo.get_cards(run_id)
        invocations = self._invocation_repo.list_for_run(run_id)
        event_ids: set[str] = set()
        for ctx in contexts:
            event_ids.update(ctx.event_ids)
            event_ids.update(ctx.eligible_event_ids)
            event_ids.update(ctx.background_event_ids)
        events = self._news_evidence.get_events(tuple(sorted(event_ids)))
        return {
            "sectors": [
                {
                    "sector_id": c.sector_id,
                    "attribution_level": c.attribution_level.value,
                    "claims": [claim.model_dump(mode="json") for claim in c.claims],
                }
                for c in cards
            ],
            "events": [asdict(ev) for ev in events],
            "invocations": [
                {
                    "stage": inv.stage,
                    "provider_id": inv.provider_id,
                    "model": inv.model,
                    "prompt_id": inv.prompt_id,
                    "prompt_version": inv.prompt_version,
                    "status": inv.status.value,
                    "total_tokens": inv.usage.total_tokens,
                    "estimated_cost_cny": str(inv.estimated_cost_cny.amount),
                    "error_code": inv.error_code,
                }
                for inv in invocations
            ],
        }

    def get_review(self, run_id: UUID) -> dict[str, Any]:
        review = self._phase1b_repo.get_review(run_id)
        if review is None:
            return {"decision": None, "revision_round": None, "issues": []}
        return {
            "decision": review.decision.value,
            "revision_round": review.revision_round,
            "issues": [issue.model_dump(mode="json") for issue in review.issues],
        }

    def _ready_draft(self, run_id: UUID) -> ArticleDraft | None:
        drafts = self._phase1b_repo.get_drafts(run_id)
        if not drafts:
            return None
        for draft in reversed(drafts):
            if draft.status is DraftStatus.READY_FOR_HUMAN_REVIEW:
                return draft
        return drafts[-1]

    def render_draft_markdown(self, run_id: UUID) -> str | None:
        draft = self._ready_draft(run_id)
        if draft is None:
            return None
        from decimal import Decimal

        from sector_pulse.application.phase1b_pipeline import Phase1BRunResult
        from sector_pulse.domain.llm import MoneyCny
        from sector_pulse.reporting.phase1b_report import render_phase1b_markdown

        result = Phase1BRunResult(
            status="READY_FOR_HUMAN_REVIEW",
            analysis_cards=(),
            outline=None,
            draft=draft,
            review=None,
            total_cost_cny=MoneyCny(amount=Decimal("0")),
            elapsed_ms=0,
        )
        return render_phase1b_markdown(result)

    def render_draft_text(self, run_id: UUID) -> str | None:
        draft = self._ready_draft(run_id)
        if draft is None:
            return None
        from decimal import Decimal

        from sector_pulse.application.phase1b_pipeline import Phase1BRunResult
        from sector_pulse.domain.llm import MoneyCny
        from sector_pulse.reporting.phase1b_report import render_phase1b_text

        result = Phase1BRunResult(
            status="READY_FOR_HUMAN_REVIEW",
            analysis_cards=(),
            outline=None,
            draft=draft,
            review=None,
            total_cost_cny=MoneyCny(amount=Decimal("0")),
            elapsed_ms=0,
        )
        return render_phase1b_text(result)
