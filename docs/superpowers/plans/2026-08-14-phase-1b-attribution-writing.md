# Phase 1B Attribution and Writing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Phase 1A.2 的行情、新闻和 EvidencePack 之上，实现确定性归因门禁、可替换 LLM Provider、多 Agent 谨慎归因、选题、成文、审核和局部返工闭环，输出一篇可供人工审核的通用社区稿。

**Architecture:** 确定性程序先构建 `AttributionContext` 并计算归因等级上限，再通过独立 Agent Port 并行生成板块分析卡，随后完成选题、成文和审核。所有模型输出必须经过 Schema、ID、数字、引用、归因和合规校验；SQLite 保存结构化产物、版本和调用审计，CLI 只装配具体 Provider。

**Tech Stack:** Python 3.12、Pydantic 2、asyncio、SQLite、PyYAML、Typer、pytest、mypy、Ruff；第一轮使用 `FixtureLLMProvider`，真实模型通过 OpenAI-compatible HTTP Provider 显式启用。

## Global Constraints

- Phase 1B 输入只允许使用已锁定 cutoff 的 Phase 1A.2 结构化事实。
- 归因等级固定为 `NO_RELIABLE_EXPLANATION < MARKET_ASSOCIATION < POSSIBLE_CATALYST < EXPLICIT_DRIVER`。
- 模型不得修改行情数字、来源等级、发布时间、引用 ID 或 `allowed_max_level`。
- 缺失发布时间或只有发现型来源时，最高只能为 `MARKET_ASSOCIATION`。
- 单个板块 Agent 失败不得取消同批其他板块任务。
- 草稿必须包含 3～6 个板块、1000～1800 个中文字符、正文来源标记和文末来源清单。
- 最多局部返工两轮；仍失败则保存产物但不得标记为可发布。
- 默认单次模型预算上限为人民币 2 元，支持配置覆盖。
- API Key 只从环境变量或本机密钥文件读取，不写入日志、数据库或报告。
- 不保存模型思维过程和新闻完整正文。
- 不实现 Web、定时调度、自动发布、社区爬取、长期偏好学习、多用户或 LangGraph。
- 关键类、状态转换、边界校验和异常路径添加中文注释。
- 遵照用户当前要求，执行阶段不进行 Git commit、push、merge；每个任务以测试检查点代替提交。

---

## File Structure

### Domain

- `backend/src/sector_pulse/domain/attribution.py`：归因等级、上下文、门禁结果、分析卡和 Claim。
- `backend/src/sector_pulse/domain/article.py`：提纲、草稿区块、来源、草稿状态和版本。
- `backend/src/sector_pulse/domain/review.py`：审核问题、审核结论和返工请求。
- `backend/src/sector_pulse/domain/llm.py`：模型请求、使用量、成本、调用结果和错误。

### Ports and configuration

- `backend/src/sector_pulse/ports/llm.py`：可替换结构化 LLM Port。
- `backend/src/sector_pulse/config/llm_config.py`：模型路由、预算和 Prompt 配置加载。
- `config/llm.yaml`：Agent 到模型的路由与预算。
- `config/prompts/*.yaml`：五类版本化 Prompt。

### Application

- `backend/src/sector_pulse/application/attribution_gate.py`：确定性归因上限和反证门禁。
- `backend/src/sector_pulse/application/agent_validation.py`：输出 Schema、ID、数字、引用、归因和合规校验。
- `backend/src/sector_pulse/application/attribution_agents.py`：板块归因并发服务及失败隔离。
- `backend/src/sector_pulse/application/editorial_agents.py`：选题、成文、审核和局部返工服务。
- `backend/src/sector_pulse/application/phase1b_pipeline.py`：端到端编排、预算和状态转换。

### Infrastructure

- `backend/src/sector_pulse/infrastructure/llm/fixture_provider.py`：确定性 Fixture Provider。
- `backend/src/sector_pulse/infrastructure/llm/openai_compatible.py`：可配置 OpenAI-compatible Provider。
- `backend/src/sector_pulse/infrastructure/llm/prompt_registry.py`：Prompt YAML 加载、版本与哈希。

### Storage and reporting

- `backend/src/sector_pulse/storage/migrations/003_phase1b.sql`：Phase 1B 数据表。
- `backend/src/sector_pulse/storage/phase1b_repository.py`：上下文、分析卡、草稿和审核持久化。
- `backend/src/sector_pulse/storage/agent_invocation_repository.py`：调用审计持久化。
- `backend/src/sector_pulse/reporting/phase1b_report.py`：JSON、Markdown 和纯文本输出。
- `backend/src/sector_pulse/cli.py`：Fixture 与真实模型显式入口。

---

### Task 1: Freeze Phase 1B Domain Contracts

**Files:**
- Create: `backend/src/sector_pulse/domain/attribution.py`
- Create: `backend/src/sector_pulse/domain/article.py`
- Create: `backend/src/sector_pulse/domain/review.py`
- Create: `backend/src/sector_pulse/domain/llm.py`
- Test: `backend/tests/unit/domain/test_attribution.py`
- Test: `backend/tests/unit/domain/test_article.py`
- Test: `backend/tests/unit/domain/test_review.py`
- Test: `backend/tests/unit/domain/test_llm.py`

**Interfaces:**
- Consumes: `EvidenceLevel`、`EvidencePack`、`SectorKind`、`NewsUse`、`QualityStatus`。
- Produces: `AttributionContext`、`AttributionGateResult`、`Claim`、`SectorAnalysisCard`、`ArticleOutline`、`ArticleDraft`、`ReviewReport`、`LLMRequest[T]`、`LLMResult[T]`。

- [ ] **Step 1: Write failing domain invariant tests**

```python
def test_analysis_card_cannot_exceed_gate() -> None:
    with pytest.raises(ValueError, match="exceeds allowed maximum"):
        SectorAnalysisCard(
            run_id=RUN_ID,
            sector_id="industry-1",
            sector_kind=SectorKind.INDUSTRY,
            allowed_max_level=EvidenceLevel.MARKET_ASSOCIATION,
            attribution_level=EvidenceLevel.POSSIBLE_CATALYST,
            confidence=Decimal("0.70"),
            conclusion="消息可能催化板块",
            supporting_evidence_ids=("event-1",),
            counter_evidence=(),
            uncertainties=("缺少直接因果表述",),
            background_event_ids=(),
            claims=(),
            forbidden_inferences=(),
        )


def test_ready_draft_requires_three_to_six_sections() -> None:
    with pytest.raises(ValueError, match="3 to 6"):
        ArticleDraft(
            draft_id=uuid4(),
            run_id=RUN_ID,
            version=1,
            status=DraftStatus.READY_FOR_HUMAN_REVIEW,
            titles=("今日板块观察",),
            introduction="导语",
            sections=(make_section("industry-1"),),
            conclusion="总结",
            risk_notice="仅供信息交流，不构成投资建议。",
            sources=(make_source("event-1"),),
            character_count=1200,
        )
```

- [ ] **Step 2: Run tests and confirm missing contracts**

Run:

```powershell
$env:PYTHONPATH = "backend/src"
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_attribution.py backend/tests/unit/domain/test_article.py backend/tests/unit/domain/test_review.py backend/tests/unit/domain/test_llm.py -q --basetemp=.test-tmp-phase1b-task1
```

Expected: collection fails because the four domain modules do not exist.

- [ ] **Step 3: Implement immutable domain models and validators**

`attribution.py` must define:

```python
LEVEL_RANK = {
    EvidenceLevel.NO_RELIABLE_EXPLANATION: 0,
    EvidenceLevel.MARKET_ASSOCIATION: 1,
    EvidenceLevel.POSSIBLE_CATALYST: 2,
    EvidenceLevel.EXPLICIT_DRIVER: 3,
}


class ClaimKind(StrEnum):
    MARKET_FACT = "MARKET_FACT"
    NEWS_FACT = "NEWS_FACT"
    ATTRIBUTION = "ATTRIBUTION"
    BACKGROUND = "BACKGROUND"


class Claim(BaseModel):
    model_config = ConfigDict(frozen=True)
    claim_id: str
    kind: ClaimKind
    text: str
    fact_keys: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    attribution_level: EvidenceLevel | None = None


class AttributionContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    sector_id: str
    sector_kind: SectorKind
    cutoff_at: datetime
    market_facts: Mapping[str, Decimal | int | str | None]
    event_ids: tuple[str, ...]
    eligible_event_ids: tuple[str, ...]
    background_event_ids: tuple[str, ...]
    excluded_event_ids: tuple[str, ...]
    source_grades: Mapping[str, SourceGrade]
    counter_evidence: tuple[str, ...]


class AttributionGateResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    sector_id: str
    allowed_max_level: EvidenceLevel
    reasons: tuple[str, ...]
    eligible_evidence_ids: tuple[str, ...]
    excluded_evidence_ids: tuple[str, ...]
    counter_evidence: tuple[str, ...]


class SectorAnalysisCard(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    sector_id: str
    sector_kind: SectorKind
    allowed_max_level: EvidenceLevel
    attribution_level: EvidenceLevel
    confidence: Decimal = Field(ge=0, le=1)
    conclusion: str
    supporting_evidence_ids: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    uncertainties: tuple[str, ...]
    background_event_ids: tuple[str, ...]
    claims: tuple[Claim, ...]
    forbidden_inferences: tuple[str, ...]

    @model_validator(mode="after")
    def enforce_level_ceiling(self) -> "SectorAnalysisCard":
        if LEVEL_RANK[self.attribution_level] > LEVEL_RANK[self.allowed_max_level]:
            raise ValueError("attribution level exceeds allowed maximum")
        return self
```

`article.py` must define `DraftStatus` values `INCOMPLETE`、`REVISE_REQUIRED`、`UNREVIEWED`、`BLOCKED`、`READY_FOR_HUMAN_REVIEW` and validate ready drafts for 3～6 unique sector sections, 1000～1800 characters, at least one source, and `version >= 1`.

`review.py` must define `ReviewDecision(PASS, REVISE, BLOCK)`、`IssueSeverity(INFO, WARNING, BLOCKING)`、`ReviewIssue`、`ReviewReport` and require `PASS` to have no blocking issues.

`llm.py` must define generic `LLMRequest[T]`、`TokenUsage`、`MoneyCny`、`LLMResult[T]`、`LLMError` and require successful results to carry parsed data and failed results to carry an error.

- [ ] **Step 4: Run domain tests, Ruff and mypy**

Run the Step 2 command, then:

```powershell
.\.venv\Scripts\python.exe -m ruff check backend/src/sector_pulse/domain backend/tests/unit/domain
.\.venv\Scripts\python.exe -m mypy backend/src/sector_pulse/domain
```

Expected: all Task 1 tests pass; Ruff and mypy report success.

- [ ] **Step 5: Record checkpoint**

Record test counts and changed files in the working update. Do not perform Git operations.

---

### Task 2: Implement Deterministic Attribution Gates

**Files:**
- Create: `backend/src/sector_pulse/application/attribution_gate.py`
- Test: `backend/tests/unit/application/test_attribution_gate.py`
- Test fixtures: `backend/tests/fixtures/attribution/gate_cases.yaml`

**Interfaces:**
- Consumes: `EvidencePack`、`NewsEvent`、`NewsDocument`、`SectorEventLink`、`SectorSnapshot`。
- Produces: `build_attribution_context(run, pack, snapshot, events, documents, links, market_move_started_at) -> AttributionContext` and `evaluate_attribution_gate(context, documents, market_move_started_at, broad_market_alternative) -> AttributionGateResult`。

- [ ] **Step 1: Add a table-driven failing gate test**

`gate_cases.yaml` must contain these exact cases:

```yaml
cases:
  - id: missing_published_at
    published_at: null
    source_grade: REPUTABLE_MEDIA
    citation_url: https://example.test/a
    event_before_move: true
    breadth_ratio: "0.80"
    expected_max: MARKET_ASSOCIATION
  - id: discovery_without_citation
    published_at: "2026-08-14T01:00:00Z"
    source_grade: DISCOVERY_ONLY
    citation_url: null
    event_before_move: true
    breadth_ratio: "0.80"
    expected_max: MARKET_ASSOCIATION
  - id: event_after_move
    published_at: "2026-08-14T02:30:00Z"
    source_grade: PRIMARY
    citation_url: https://example.test/b
    event_before_move: false
    breadth_ratio: "0.80"
    expected_max: MARKET_ASSOCIATION
  - id: broad_primary_response
    published_at: "2026-08-14T01:00:00Z"
    source_grade: PRIMARY
    citation_url: https://example.test/c
    event_before_move: true
    breadth_ratio: "0.80"
    expected_max: EXPLICIT_DRIVER
  - id: single_stock_only
    published_at: "2026-08-14T01:00:00Z"
    source_grade: PRIMARY
    citation_url: https://example.test/d
    event_before_move: true
    breadth_ratio: "0.10"
    expected_max: POSSIBLE_CATALYST
```

The test loads each case, builds a context and asserts the exact `allowed_max_level` and reason code.

- [ ] **Step 2: Run the gate test and confirm failure**

Run:

```powershell
$env:PYTHONPATH = "backend/src"
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_attribution_gate.py -q --basetemp=.test-tmp-phase1b-task2
```

Expected: import failure for `attribution_gate`.

- [ ] **Step 3: Implement context construction and ordered gates**

Use the following order so later rules can only lower, never raise, the ceiling:

```python
def lower(current: EvidenceLevel, proposed: EvidenceLevel) -> EvidenceLevel:
    return proposed if LEVEL_RANK[proposed] < LEVEL_RANK[current] else current


def evaluate_attribution_gate(
    context: AttributionContext,
    documents: Mapping[str, NewsDocument],
    market_move_started_at: datetime | None,
    broad_market_alternative: bool,
) -> AttributionGateResult:
    maximum = EvidenceLevel.EXPLICIT_DRIVER
    reasons: list[str] = []
    if not context.eligible_event_ids:
        maximum = EvidenceLevel.NO_RELIABLE_EXPLANATION
        reasons.append("NO_ELIGIBLE_EVENT")
    if has_missing_publication_time:
        maximum = lower(maximum, EvidenceLevel.MARKET_ASSOCIATION)
        reasons.append("MISSING_PUBLICATION_TIME")
    if discovery_only_without_citation:
        maximum = lower(maximum, EvidenceLevel.MARKET_ASSOCIATION)
        reasons.append("DISCOVERY_ONLY_WITHOUT_CITATION")
    if event_after_market_move:
        maximum = lower(maximum, EvidenceLevel.MARKET_ASSOCIATION)
        reasons.append("EVENT_AFTER_MARKET_MOVE")
    if single_stock_without_breadth:
        maximum = lower(maximum, EvidenceLevel.POSSIBLE_CATALYST)
        reasons.append("INSUFFICIENT_SECTOR_BREADTH")
    if broad_market_alternative:
        maximum = lower(maximum, EvidenceLevel.POSSIBLE_CATALYST)
        reasons.append("BROAD_MARKET_ALTERNATIVE")
    return AttributionGateResult(
        run_id=context.run_id,
        sector_id=context.sector_id,
        allowed_max_level=maximum,
        reasons=tuple(reasons),
        eligible_evidence_ids=context.eligible_event_ids,
        excluded_evidence_ids=context.excluded_event_ids,
        counter_evidence=context.counter_evidence,
    )
```

`build_attribution_context()` must reject an unlocked run cutoff and must exclude documents whose `use_at(cutoff)` is `EXCLUDED`.

- [ ] **Step 4: Verify all gate branches**

Run Task 2 tests, Ruff and mypy for the new module. Expected: every YAML case passes and no static errors remain.

- [ ] **Step 5: Record checkpoint**

Report the covered reason codes and test count. Do not perform Git operations.

---

### Task 3: Add Prompt Registry, LLM Port and Fixture Provider

**Files:**
- Create: `backend/src/sector_pulse/ports/llm.py`
- Create: `backend/src/sector_pulse/config/llm_config.py`
- Create: `backend/src/sector_pulse/infrastructure/llm/__init__.py`
- Create: `backend/src/sector_pulse/infrastructure/llm/prompt_registry.py`
- Create: `backend/src/sector_pulse/infrastructure/llm/fixture_provider.py`
- Create: `config/llm.yaml`
- Create: `config/prompts/attribution.yaml`
- Create: `config/prompts/editorial.yaml`
- Create: `config/prompts/writing.yaml`
- Create: `config/prompts/review.yaml`
- Create: `config/prompts/revision.yaml`
- Test: `backend/tests/unit/config/test_llm_config.py`
- Test: `backend/tests/unit/infrastructure/test_prompt_registry.py`
- Test: `backend/tests/unit/infrastructure/test_fixture_llm_provider.py`

**Interfaces:**
- Consumes: Task 1 domain response models.
- Produces: `LLMPort.generate_structured()`、`PromptRegistry.get(prompt_id)`、`FixtureLLMProvider`。

- [ ] **Step 1: Write failing configuration and fixture tests**

```python
def test_prompt_hash_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "prompt.yaml"
    path.write_text("prompt_id: attribution\nversion: '1.0.0'\nsystem: test\n", encoding="utf-8")
    first = PromptRegistry(tmp_path).get("attribution")
    second = PromptRegistry(tmp_path).get("attribution")
    assert first.content_sha256 == second.content_sha256


async def test_fixture_provider_returns_registered_response() -> None:
    provider = FixtureLLMProvider({"sector-analysis:industry-1": VALID_CARD})
    result = await provider.generate_structured(make_request("sector-analysis:industry-1"))
    assert result.data == VALID_CARD
    assert result.usage.total_tokens == 0
    assert result.estimated_cost_cny.amount == Decimal("0")
```

- [ ] **Step 2: Run tests and confirm import failures**

Run the three Task 3 test files with project-owned `--basetemp`. Expected: missing modules.

- [ ] **Step 3: Implement configuration and Port**

`llm.yaml` must provide:

```yaml
version: "2026-08-14.1"
budget_cny_per_run: "2.00"
max_attribution_concurrency: 4
max_revision_rounds: 2
routes:
  attribution: {provider: fixture, model: fixture-low}
  editorial: {provider: fixture, model: fixture-high}
  writing: {provider: fixture, model: fixture-high}
  review: {provider: fixture, model: fixture-review}
  revision: {provider: fixture, model: fixture-high}
```

`LLMPort` signature:

```python
class LLMPort(Protocol):
    async def generate_structured(self, request: LLMRequest[T]) -> LLMResult[T]: ...
    async def health_check(self) -> LLMHealth: ...
    def estimate_cost(self, usage: TokenUsage, model: str) -> MoneyCny: ...
```

`PromptRegistry` must load YAML with `yaml.safe_load`, validate required fields, hash normalized UTF-8 content and reject duplicate `prompt_id` values.

- [ ] **Step 4: Implement deterministic Fixture Provider**

Fixture lookup key is `request.fixture_key`. Missing keys return `LLMError(code="FIXTURE_RESPONSE_MISSING", retriable=False)`; successful responses are validated against `request.response_model` before returning.

- [ ] **Step 5: Run Task 3 tests and static checks**

Expected: configuration, registry and fixture tests pass; Ruff and mypy pass.

- [ ] **Step 6: Record checkpoint**

List Prompt IDs, config version and Fixture behavior. Do not perform Git operations.

---

### Task 4: Implement Output Validation and Agent Services

**Files:**
- Create: `backend/src/sector_pulse/application/agent_validation.py`
- Create: `backend/src/sector_pulse/application/attribution_agents.py`
- Create: `backend/src/sector_pulse/application/editorial_agents.py`
- Test: `backend/tests/unit/application/test_agent_validation.py`
- Test: `backend/tests/unit/application/test_attribution_agents.py`
- Test: `backend/tests/unit/application/test_editorial_agents.py`

**Interfaces:**
- Consumes: Tasks 1～3 contracts, `LLMPort`, `PromptRegistry` and gate results.
- Produces: `validate_analysis_card()`、`run_attribution_agents()`、`run_editorial_agent()`、`run_writing_agent()`、`run_review_agent()`、`revise_sections()`。

- [ ] **Step 1: Write failing validation tests**

```python
def test_rejects_unknown_evidence_id() -> None:
    with pytest.raises(AgentOutputViolation) as error:
        validate_analysis_card(
            card=make_card(supporting_evidence_ids=("invented-event",)),
            gate=make_gate(eligible_evidence_ids=("event-1",)),
            context=CONTEXT,
        )
    assert error.value.code == "UNKNOWN_EVIDENCE_ID"


def test_rejects_changed_market_number() -> None:
    claim = make_claim(text="板块上涨9.9%", fact_keys=("pct_change",))
    with pytest.raises(AgentOutputViolation) as error:
        validate_claim_numbers(claim, {"pct_change": Decimal("3.2")})
    assert error.value.code == "MARKET_NUMBER_MISMATCH"
```

Also test `ATTRIBUTION_LEVEL_EXCEEDED`、`UNKNOWN_CLAIM_ID`、`MISSING_SOURCE_REFERENCE` and prohibited phrases such as “建议重仓”“必涨”“稳赚”。

- [ ] **Step 2: Run tests and confirm missing services**

Run the three Task 4 test files. Expected: import failures.

- [ ] **Step 3: Implement pure validators**

`AgentOutputViolation` fields are `code`、`message`、`location` and `blocking=True`。Number validation must compare normalized `Decimal` values from the Claim against the named fact key; it must never rely only on a regular-expression blacklist.

- [ ] **Step 4: Implement concurrent attribution service**

```python
async def run_attribution_agents(
    contexts: Sequence[AttributionContext],
    gates: Mapping[str, AttributionGateResult],
    llm: LLMPort,
    prompt: PromptDefinition,
    concurrency: int = 4,
) -> tuple[AttributionAgentResult, ...]:
```

Use one semaphore, preserve input order, retry only retriable LLM errors once, and convert persistent single-sector failures into a validated fallback card with `NO_RELIABLE_EXPLANATION` and reason `AGENT_FAILED`.

- [ ] **Step 5: Implement editorial, writing, review and revision services**

Each service must accept only the previous stage's validated models. `revise_sections()` receives the prior draft, blocking issues and selected section IDs; it returns a new draft with `version + 1` while preserving unchanged section hashes.

- [ ] **Step 6: Run Task 4 tests and static checks**

Expected: concurrency peak never exceeds 4, result order is stable, invalid IDs/numbers/levels are rejected, and local revision changes only targeted sections.

- [ ] **Step 7: Record checkpoint**

Report validator codes, concurrency test and revision isolation evidence. Do not perform Git operations.

---

### Task 5: Persist Phase 1B Artifacts and Invocation Audit

**Files:**
- Create: `backend/src/sector_pulse/storage/migrations/003_phase1b.sql`
- Create: `backend/src/sector_pulse/storage/phase1b_repository.py`
- Create: `backend/src/sector_pulse/storage/agent_invocation_repository.py`
- Modify: `backend/src/sector_pulse/storage/evidence_repository.py`
- Modify: `backend/src/sector_pulse/storage/news_repository.py`
- Test: `backend/tests/unit/storage/test_phase1b_schema.py`
- Test: `backend/tests/integration/test_phase1b_repository.py`

**Interfaces:**
- Consumes: all Task 1 domain models and invocation metadata from Tasks 3～4.
- Produces: `SQLitePhase1BRepository` and `SQLiteAgentInvocationRepository`。

- [ ] **Step 1: Write failing schema and round-trip tests**

```python
def test_phase1b_schema_has_all_tables(database: SQLiteDatabase) -> None:
    database.initialize()
    names = table_names(database)
    assert {
        "attribution_contexts", "attribution_gate_results", "sector_analysis_cards",
        "claims", "article_outlines", "article_drafts", "article_sections",
        "article_sources", "review_reports", "review_issues", "agent_invocations",
    } <= names


def test_draft_versions_are_append_only(repository: SQLitePhase1BRepository) -> None:
    repository.save_draft(make_draft(version=1))
    repository.save_draft(make_draft(version=2))
    assert [item.version for item in repository.list_drafts(DRAFT_ID)] == [1, 2]
```

- [ ] **Step 2: Run tests and confirm migration/repository absence**

Expected: table assertion and imports fail.

- [ ] **Step 3: Add migration with foreign keys and uniqueness**

Required keys:

- context/gate/card: `(run_id, sector_id, sector_kind)`;
- Claim: `(run_id, claim_id)`;
- outline: `outline_id` plus `run_id`;
- draft: `(draft_id, version)`;
- section: `(draft_id, version, section_id)`;
- source: `(draft_id, version, source_id)`;
- review: `(review_id, draft_id, draft_version)`;
- invocation: `invocation_id` plus indexes on `(run_id, stage)` and `(provider_id, model)`.

Every JSON payload column must have a SHA-256 companion. Token counts and cost use integer tokens and decimal strings respectively.

- [ ] **Step 4: Implement transactional repositories**

Repositories expose explicit methods `save_contexts`、`save_gate_results`、`save_cards`、`save_outline`、`save_draft`、`save_review` and `save_invocations`。Add `SQLiteEvidenceRepository.list_by_run(run_id) -> tuple[EvidencePack, ...]`、`SQLiteNewsRepository.get_events(event_ids) -> tuple[NewsEvent, ...]` and `list_documents_for_events(event_ids) -> tuple[NewsDocument, ...]` so the pipeline first loads the run's EvidencePack event IDs and never queries SQLite directly. A draft save writes header, sections and sources in one transaction. Updating an existing `(draft_id, version)` with a different payload hash must raise `ImmutableDraftVersionError`.

- [ ] **Step 5: Run storage tests and static checks**

Expected: migration is idempotent, round trips preserve Pydantic models, and version immutability test passes.

- [ ] **Step 6: Record checkpoint**

Report applied schema version, tables and round-trip test results. Do not perform Git operations.

---

### Task 6: Build the Phase 1B Pipeline with Budget and Recovery Boundaries

**Files:**
- Create: `backend/src/sector_pulse/application/phase1b_pipeline.py`
- Test: `backend/tests/integration/test_phase1b_pipeline.py`
- Fixtures: `backend/tests/fixtures/phase1b/fixture_responses.json`

**Interfaces:**
- Consumes: Phase 1A.2 structured inputs, Tasks 1～5 services and repositories.
- Produces: `run_phase1b_pipeline(dependencies, request) -> Phase1BRunResult`。

- [ ] **Step 1: Create complete deterministic Fixture responses**

The fixture file must include keys for eight attribution cards, one editorial outline, one first draft, one review with a section-specific issue, one revised section and one final PASS review. Include at least one `NO_RELIABLE_EXPLANATION` card and one `MARKET_ASSOCIATION` card.

- [ ] **Step 2: Write failing end-to-end tests**

```python
async def test_pipeline_produces_reviewable_draft(dependencies) -> None:
    result = await run_phase1b_pipeline(dependencies, make_request())
    assert len(result.analysis_cards) == 8
    assert 3 <= len(result.draft.sections) <= 6
    assert 1000 <= result.draft.character_count <= 1800
    assert result.draft.version == 2
    assert result.draft.status is DraftStatus.READY_FOR_HUMAN_REVIEW
    assert result.review.decision is ReviewDecision.PASS
    assert result.total_cost_cny.amount <= Decimal("2.00")


async def test_budget_stops_before_next_agent_call(dependencies) -> None:
    dependencies.budget = MoneyCny(amount=Decimal("0.01"))
    result = await run_phase1b_pipeline(dependencies, make_request())
    assert result.status is PipelineStatus.BUDGET_EXCEEDED
    assert result.draft is None
```

Also test market/news quality blocked, fewer than three valid cards, writing failure, review failure, and two unsuccessful revision rounds.

- [ ] **Step 3: Run tests and confirm pipeline absence**

Expected: import failure for `phase1b_pipeline`.

- [ ] **Step 4: Implement explicit dependency container and request**

```python
@dataclass(frozen=True)
class Phase1BDependencies:
    llm: LLMPort
    prompts: PromptRegistry
    market_repository: SQLiteMarketSnapshotRepository
    evidence_repository: SQLiteEvidenceRepository
    news_repository: SQLiteNewsRepository
    repository: SQLitePhase1BRepository
    invocation_repository: SQLiteAgentInvocationRepository
    config: LLMRuntimeConfig


class Phase1BRequest(BaseModel):
    run_id: UUID
    requested_at: datetime
    output_dir: Path
```

The pipeline must not instantiate providers or repositories internally.

- [ ] **Step 5: Implement state transitions and budget checks**

`PipelineStatus` values: `RUNNING`、`ATTRIBUTION_BLOCKED`、`DRAFT_GENERATION_FAILED`、`UNREVIEWED`、`REVISE_REQUIRED`、`BUDGET_EXCEEDED`、`READY_FOR_HUMAN_REVIEW`。

Before every LLM call, check estimated remaining budget. After every call, add actual usage cost and persist the invocation. A budget breach stops before the next call and does not mutate the most recent valid artifact.

- [ ] **Step 6: Implement orchestration order**

The exact order is:

```text
load Phase 1A.2 inputs
→ build contexts
→ evaluate gates
→ persist contexts and gates
→ run attribution agents concurrently
→ validate and persist cards/claims
→ editorial agent or deterministic fallback
→ persist outline
→ writing agent
→ validate and persist draft v1
→ review agent
→ at most two targeted revision loops
→ persist final review and result
```

- [ ] **Step 7: Run pipeline tests and static checks**

Expected: all success and failure state tests pass, Fixture output is byte-stable between two identical runs after replacing generated UUIDs with injected IDs, and no call occurs after budget exhaustion.

- [ ] **Step 8: Record checkpoint**

Report end-to-end status, revision count, deterministic hash and budget test. Do not perform Git operations.

---

### Task 7: Render Draft Artifacts and Add CLI

**Files:**
- Create: `backend/src/sector_pulse/reporting/phase1b_report.py`
- Modify: `backend/src/sector_pulse/cli.py`
- Test: `backend/tests/unit/reporting/test_phase1b_report.py`
- Test: `backend/tests/integration/test_phase1b_cli.py`

**Interfaces:**
- Consumes: `Phase1BRunResult` and final `ArticleDraft`。
- Produces: `render_phase1b_markdown()`、`render_phase1b_text()`、`write_phase1b_artifacts()` and CLI `phase1b-draft`。

- [ ] **Step 1: Write failing renderer tests**

```python
def test_markdown_contains_inline_and_end_sources() -> None:
    markdown = render_phase1b_markdown(READY_RESULT)
    assert "[来源1]" in markdown
    assert "## 来源清单" in markdown
    assert READY_RESULT.draft.sources[0].citation_url in markdown
    assert "READY_FOR_HUMAN_REVIEW" in markdown


def test_blocked_result_cannot_render_publishable_text() -> None:
    with pytest.raises(ValueError, match="not ready for human review"):
        render_phase1b_text(BLOCKED_RESULT)
```

- [ ] **Step 2: Run tests and confirm missing renderer/command**

Expected: imports fail and CLI help lacks `phase1b-draft`.

- [ ] **Step 3: Implement safe renderers**

Write these paths without overwrite:

```text
data/phase1b/<date>/<run_id>/result.json
data/phase1b/<date>/<run_id>/draft.md
data/phase1b/<date>/<run_id>/draft.txt
data/phase1b/<date>/<run_id>/review.json
```

`draft.md` and `draft.txt` may only be produced for `READY_FOR_HUMAN_REVIEW`; blocked runs still write `result.json` and `review.json`.

- [ ] **Step 4: Add Fixture-first CLI**

```python
@app.command("phase1b-draft")
def phase1b_draft(
    run_id: UUID = typer.Option(..., "--run-id"),
    provider: str = typer.Option("fixture", "--provider"),
    output_dir: Path = typer.Option(Path("data/phase1b")),
    database_path: Path = typer.Option(Path("data/sector-pulse.db")),
    llm_config: Path = typer.Option(Path("config/llm.yaml")),
    fixture_responses: Path = typer.Option(
        Path("backend/tests/fixtures/phase1b/fixture_responses.json")
    ),
    live_llm_consent: Path = typer.Option(Path(".live-llm-consent")),
) -> None:
```

`provider=fixture` never reads an API Key. Any other provider requires `.live-llm-consent` before provider construction and returns a clear configuration error if the required environment variable is absent.

- [ ] **Step 5: Run renderer, CLI and help tests**

Expected: ready run writes all four artifacts; blocked run writes only two audit artifacts; CLI help lists the command and consent behavior passes.

- [ ] **Step 6: Record checkpoint**

Report artifact paths and CLI fixture invocation. Do not perform Git operations.

---

### Task 8: Add OpenAI-compatible Provider and Final Acceptance

**Files:**
- Create: `backend/src/sector_pulse/infrastructure/llm/openai_compatible.py`
- Test: `backend/tests/unit/infrastructure/test_openai_compatible_provider.py`
- Create: `backend/tests/live/test_phase1b_llm_live.py`
- Modify: `backend/tests/conftest.py`
- Create: `docs/phase1b/README.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: Task 3 `LLMPort` and Task 7 CLI configuration.
- Produces: HTTP Provider, explicit live-model acceptance test and operator documentation.

- [ ] **Step 1: Add the HTTP dependency within existing version policy**

Add `httpx>=0.28,<1` to project dependencies. Do not add a vendor SDK; the Provider targets the OpenAI-compatible JSON contract directly.

- [ ] **Step 2: Write mocked HTTP tests**

Test exact behaviors:

- Authorization header is constructed from a `SecretStr` and never appears in exceptions;
- `base_url` joins with `/chat/completions` once;
- timeout returns `LLM_TIMEOUT` with `retriable=True`;
- HTTP 429 returns `LLM_RATE_LIMITED` with `retriable=True`;
- HTTP 400 returns `LLM_REQUEST_REJECTED` with `retriable=False`;
- invalid JSON/schema returns `LLM_STRUCTURED_OUTPUT_INVALID`;
- usage and configured per-million-token prices produce exact `Decimal` CNY cost.

- [ ] **Step 3: Implement the Provider**

Constructor:

```python
class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        timeout_seconds: float,
        pricing: Mapping[str, ModelPrice],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._pricing = dict(pricing)
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
```

When a response model exposes JSON Schema, send `response_format={"type": "json_schema", "json_schema": {"name": request.response_model.__name__, "schema": request.response_model.model_json_schema(), "strict": True}}`; otherwise request JSON object output and apply local Pydantic validation. Error messages may include status code and provider request ID but must exclude headers, API Key and full response bodies.

- [ ] **Step 4: Add explicitly gated live test**

The test requires all of:

- `--run-live-llm`;
- `.live-llm-consent` file;
- `SECTOR_PULSE_LLM_API_KEY` environment variable;
- `SECTOR_PULSE_LLM_BASE_URL` environment variable.

It sends one small attribution fixture and asserts only Schema validity, allowed evidence IDs, attribution ceiling, usage presence and cost below the configured per-test cap. It must not assert prose equality.

- [ ] **Step 5: Document local configuration without secrets**

`docs/phase1b/README.md` must include Fixture CLI usage, environment variable names, consent creation, live test command, monthly cost assumptions, expected artifacts and the statement that the output requires human review and is not investment advice.

- [ ] **Step 6: Run final offline verification**

Run:

```powershell
$env:PYTHONPATH = "backend/src"
.\.venv\Scripts\python.exe -m pytest backend/tests --ignore=backend/tests/live -q --basetemp=.test-tmp-phase1b-final
.\.venv\Scripts\python.exe -m ruff check backend/src backend/tests --exclude backend/tests/live
.\.venv\Scripts\python.exe -m mypy backend/src
$env:UV_CACHE_DIR = "D:\work\project\SectorPulse\.uv-cache"
uv build
```

Expected: all offline tests pass, Ruff and mypy report success, and wheel/sdist build successfully.

- [ ] **Step 7: Run optional live-model acceptance only when configured**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/live/test_phase1b_llm_live.py --run-live-llm -q
```

Expected when configured: live test passes and reports usage/cost without leaking secrets. When configuration is absent, report “not run”; do not call the network and do not claim live acceptance.

- [ ] **Step 8: Produce acceptance summary**

Report separately:

- Fixture/offline pipeline status and test count;
- real-model live status;
- generated artifact paths;
- actual model cost when live test ran;
- any remaining baseline network failures from Phase 1A.2;
- confirmation that Git was not modified beyond working-tree files.

Do not perform Git operations.

---

## Final Acceptance Checklist

- [ ] 8～12 个候选可以稳定形成结构化分析卡。
- [ ] 归因等级越级被程序拒绝，不依赖 Prompt 自律。
- [ ] 未来新闻、缺失时间、发现型来源和反证均触发正确门禁。
- [ ] 单板块失败隔离且顺序稳定。
- [ ] 选题输出 3～6 个板块，文章为 1000～1800 字。
- [ ] 每个数字、Claim 和来源均可追溯。
- [ ] 审核只局部返工且最多两轮。
- [ ] 未审核、超预算或阻断草稿不能输出可发布文本。
- [ ] SQLite 保存完整结构化产物、版本和调用审计。
- [ ] Fixture 运行不需要 API Key 且结果可重复。
- [ ] 真实模型调用必须经过显式 consent 和环境变量门禁。
- [ ] JSON、Markdown、纯文本和审核报告输出符合状态规则。
- [ ] 全量离线测试、Ruff、mypy 和构建通过。
- [ ] live 结果与离线结果分开报告，不伪造成功。
