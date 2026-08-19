# Phase 2B Review Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不可变草稿版本之上实现结构化 Patch、证据裁决、局部重写、治理门禁和显式偏好采纳，形成五分钟人工审核路径。

**Architecture:** `DraftEditingService` 负责 Patch/版本/Diff/回滚，`EvidenceDecisionService` 负责证据裁决和受影响段落，`RewriteService` 复用现有 OpenAI 兼容 LLM 生成候选段落，`GovernanceService` 负责数字、来源、归因和合规检查。SQLite 保存所有版本、Patch、裁决、重写、治理检查和偏好审计。

**Tech Stack:** Python 3.12、Pydantic v2、FastAPI、SQLite WAL、现有 LLM Provider、React/TypeScript/Vitest。

## Global Constraints

- `article_drafts` 版本不可变；新编辑必须产生新版本，旧版本不能静默覆盖。
- Patch 只允许标题、导语、段落 heading/body、结论和风险提示路径。
- 不允许修改行情事实、来源 URL、证据原文、Claim/Source 绑定或 cutoff。
- 证据决策只能是 `KEEP`、`DOWNGRADE`、`REJECT`；驳回后无替代证据必须 `NO_RELIABLE_EXPLANATION` 或删除断言。
- 局部重写必须继承可信来源绑定，不能让 LLM 新增未经验证 source ID。
- 偏好只有用户显式采纳后才影响未来 Prompt。
- 不接入第三方账号或自动发布。
- 每个新函数先写失败测试，再写最小实现；每个任务独立提交。

---

## 文件与职责地图

| 文件 | 职责 |
|---|---|
| `backend/src/sector_pulse/domain/editing.py` | Patch、证据决策、重写和治理领域模型 |
| `backend/src/sector_pulse/storage/migrations/009_phase2b_governance.sql` | Phase 2B 表和唯一约束 |
| `backend/src/sector_pulse/storage/draft_edit_repository.py` | 版本、Patch、Diff 和回滚持久化 |
| `backend/src/sector_pulse/storage/governance_repository.py` | 证据、重写、治理、偏好审计存储 |
| `backend/src/sector_pulse/application/draft_editing_service.py` | Patch 应用、冲突检测、版本创建 |
| `backend/src/sector_pulse/application/evidence_decision_service.py` | 证据裁决和受影响段落计算 |
| `backend/src/sector_pulse/application/rewrite_service.py` | 受限上下文局部重写 |
| `backend/src/sector_pulse/application/governance_service.py` | 四类门禁和核准状态 |
| `backend/src/sector_pulse/web/editing_schemas.py` / `app.py` | API DTO 与路由 |
| `web/src/pages/tabs/DraftTab.tsx` | 结构化编辑、证据卡、Diff、核准和复制 |
| `web/src/editingApi.ts` | 编辑/证据/重写/治理 API 客户端 |

## Task 1: Add editing domain and migration

**Files:**
- Create: `backend/src/sector_pulse/domain/editing.py`
- Create: `backend/src/sector_pulse/storage/migrations/009_phase2b_governance.sql`
- Test: `backend/tests/unit/domain/test_editing.py`, `backend/tests/unit/storage/test_phase2b_schema.py`

- [ ] **Step 1: Write failing model and schema tests**

```python
def test_patch_rejects_source_and_cutoff_paths():
    with pytest.raises(ValueError, match="path is not editable"):
        DraftPatch(path="sections/s1/source_ids", old_value_hash="x", value=["new"])

def test_phase2b_migration_creates_governance_tables(database):
    database.initialize()
    assert {"draft_patches", "evidence_decisions", "rewrite_requests", "governance_checks"} <= database.table_names()
```

- [ ] **Step 2: Run and observe expected failure**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_editing.py backend/tests/unit/storage/test_phase2b_schema.py -q -p no:cacheprovider`

Expected: FAIL because editing models, migration and `table_names()` support are missing.

- [ ] **Step 3: Implement frozen Pydantic models and migration**

Define `DraftPatch`, `EvidenceDecision`, `RewriteRequest`, `GovernanceCheck`, `PreferenceCandidate`, and `PreferenceVersion`; validate `KEEP/DOWNGRADE/REJECT`, editable path prefixes and non-empty old hash. Add foreign keys, JSON payload hashes, ordered Patch operations and immutable governance rows.

- [ ] **Step 4: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_editing.py backend/tests/unit/storage/test_phase2b_schema.py -q -p no:cacheprovider`

```bash
git add backend/src/sector_pulse/domain/editing.py backend/src/sector_pulse/storage/migrations/009_phase2b_governance.sql backend/tests/unit/domain/test_editing.py backend/tests/unit/storage/test_phase2b_schema.py
git commit -m "feat: add phase 2b editing domain"
```

## Task 2: Implement immutable version/Patch repository

**Files:**
- Create: `backend/src/sector_pulse/storage/draft_edit_repository.py`
- Modify: `backend/src/sector_pulse/storage/phase1b_repository.py`
- Test: `backend/tests/unit/storage/test_draft_edit_repository.py`

- [ ] **Step 1: Write failing repository tests**

```python
def test_patch_creates_new_version_without_mutating_base(repository, draft):
    result = repository.apply_patch(draft, base_version=1, operations=[replace_body])
    assert result.version == 2
    assert repository.get_version(draft.draft_id, 1).sections[0].body != result.sections[0].body

def test_stale_base_version_is_conflict(repository, draft):
    with pytest.raises(DraftVersionConflict):
        repository.apply_patch(draft, base_version=0, operations=[])
```

- [ ] **Step 2: Verify red**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_draft_edit_repository.py -q -p no:cacheprovider`

Expected: FAIL because the repository and conflict exception do not exist.

- [ ] **Step 3: Implement transactional version creation**

Load the latest `ArticleDraft`, verify `base_version` and each old-value hash, apply only allowed paths, create `version + 1`, run `ArticleDraft` validators, insert the full draft plus sections/sources with `INSERT` only, and save ordered Patch operations and hashes. `rollback` creates a new version copied from a historical version.

- [ ] **Step 4: Run focused tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_draft_edit_repository.py backend/tests/unit/storage/test_phase1b_repository.py -q -p no:cacheprovider`

```bash
git add backend/src/sector_pulse/storage/draft_edit_repository.py backend/src/sector_pulse/storage/phase1b_repository.py backend/tests/unit/storage/test_draft_edit_repository.py
git commit -m "feat: persist immutable draft edits"
```

## Task 3: Evidence decisions and governed local rewrite

**Files:**
- Create: `backend/src/sector_pulse/application/evidence_decision_service.py`
- Create: `backend/src/sector_pulse/application/rewrite_service.py`
- Create: `backend/src/sector_pulse/storage/governance_repository.py`
- Test: `backend/tests/unit/application/test_evidence_decision_service.py`, `backend/tests/unit/application/test_rewrite_service.py`

- [ ] **Step 1: Write failing decision/rewrite tests**

```python
def test_rejecting_source_marks_only_linked_sections_for_rewrite(service):
    affected = service.record("source-1", "REJECT", "not relevant")
    assert affected == {"section-1"}

async def test_rewrite_cannot_add_unverified_source(rewrite_service):
    result = await rewrite_service.rewrite(section, rejected_source_ids={"source-1"})
    assert result.source_ids == section.source_ids - {"source-1"}
```

- [ ] **Step 2: Verify red**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_evidence_decision_service.py backend/tests/unit/application/test_rewrite_service.py -q -p no:cacheprovider`

Expected: FAIL because decision and rewrite services do not exist.

- [ ] **Step 3: Implement constrained rewrite**

Resolve source/claim IDs only from persisted Phase 1B evidence, calculate impacted sections, persist decisions immutably, build a prompt from target section plus validated facts and accepted sources, parse an `ArticleSection` candidate, intersect returned source IDs with trusted IDs, and create a new draft version. Record every invocation; failures preserve the base version.

- [ ] **Step 4: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_evidence_decision_service.py backend/tests/unit/application/test_rewrite_service.py -q -p no:cacheprovider`

```bash
git add backend/src/sector_pulse/application/evidence_decision_service.py backend/src/sector_pulse/application/rewrite_service.py backend/src/sector_pulse/storage/governance_repository.py backend/tests/unit/application/test_evidence_decision_service.py backend/tests/unit/application/test_rewrite_service.py
git commit -m "feat: add governed evidence decisions and rewrites"
```

## Task 4: Governance gates and approval

**Files:**
- Create: `backend/src/sector_pulse/application/governance_service.py`
- Test: `backend/tests/unit/application/test_governance_service.py`

- [ ] **Step 1: Write failing gate tests**

```python
def test_governance_blocks_unbound_source(draft, governance):
    report = governance.check(draft)
    assert report.status == "FAIL"
    assert any(issue.code == "SOURCE_UNBOUND" for issue in report.issues)

def test_governance_blocks_forbidden_trading_language(draft, governance):
    report = governance.check(draft.model_copy(update={"conclusion": "建议买入"}))
    assert report.status == "FAIL"
```

- [ ] **Step 2: Verify red**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_governance_service.py -q -p no:cacheprovider`

Expected: FAIL because governance service does not exist.

- [ ] **Step 3: Implement checks and approval transition**

Check numeric/time consistency, source completeness, attribution maximum level and forbidden trading/publishing language. Save immutable checks; approval requires all PASS and a current target version.

- [ ] **Step 4: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_governance_service.py -q -p no:cacheprovider`

```bash
git add backend/src/sector_pulse/application/governance_service.py backend/tests/unit/application/test_governance_service.py
git commit -m "feat: add phase 2b governance gates"
```

## Task 5: Add editing, evidence, rewrite and preference APIs

**Files:**
- Create: `backend/src/sector_pulse/web/editing_schemas.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Test: `backend/tests/integration/test_phase2b_api.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_patch_and_approval_are_versioned(client, draft_id):
    response = client.post(f"/api/runs/run-1/drafts/{draft_id}/patches", json={"base_version": 1, "operations": []})
    assert response.status_code == 201
    assert response.json()["version"] == 2
```

- [ ] **Step 2: Verify red**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_phase2b_api.py -q -p no:cacheprovider`

Expected: FAIL with 404 because Phase 2B routes do not exist.

- [ ] **Step 3: Implement DTOs and routes**

Add version list, Diff, Patch, rollback, evidence decision, rewrite, governance, approve, preference candidate/adopt/rollback endpoints. Require `Idempotency-Key` and `base_version` on mutations; map stale versions to 409, validation to 422 and missing drafts to 404.

- [ ] **Step 4: Run API regression and commit**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_phase2b_api.py backend/tests/integration/test_web_api.py -q -p no:cacheprovider`

```bash
git add backend/src/sector_pulse/web/editing_schemas.py backend/src/sector_pulse/web/app.py backend/tests/integration/test_phase2b_api.py
git commit -m "feat: expose phase 2b review APIs"
```

## Task 6: Build the five-minute review UI

**Files:**
- Create: `web/src/editingApi.ts`
- Modify: `web/src/pages/tabs/DraftTab.tsx`
- Create: `web/src/pages/tabs/ReviewEditor.tsx`
- Create: `web/src/pages/tabs/EvidenceDecisionCard.tsx`
- Tests: `web/src/pages/tabs/ReviewEditor.test.tsx`, `web/src/pages/tabs/EvidenceDecisionCard.test.tsx`

- [ ] **Step 1: Write failing UI tests**

```tsx
it('edits one section and shows unsaved patch', async () => {
  render(<ReviewEditor />)
  await userEvent.click(screen.getByRole('button', { name: '编辑' }))
  expect(screen.getByText('未保存修改')).toBeInTheDocument()
})

it('offers KEEP DOWNGRADE REJECT evidence decisions', () => {
  render(<EvidenceDecisionCard />)
  expect(screen.getByRole('button', { name: '保留' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '降级' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '驳回' })).toBeInTheDocument()
})
```

- [ ] **Step 2: Verify red**

Run: `npm.cmd test -- --run src/pages/tabs/ReviewEditor.test.tsx src/pages/tabs/EvidenceDecisionCard.test.tsx`

Expected: FAIL because the editor and evidence card do not exist.

- [ ] **Step 3: Implement structured editing UI**

Keep local Patch operations until save, show base/current version, display evidence beside linked paragraphs, invoke local rewrite only for impacted sections, render governance failures before approval, and keep copy Markdown/text as the only publishing-adjacent actions.

- [ ] **Step 4: Run frontend suite/build and commit**

Run: `npm.cmd test -- --run; npm.cmd run build`

```bash
git add web/src/editingApi.ts web/src/pages/tabs/DraftTab.tsx web/src/pages/tabs/ReviewEditor.tsx web/src/pages/tabs/EvidenceDecisionCard.tsx web/src/pages/tabs/ReviewEditor.test.tsx web/src/pages/tabs/EvidenceDecisionCard.test.tsx
git commit -m "feat: add phase 2b review editor"
```

## Task 7: Preference governance and end-to-end acceptance

**Files:**
- Create: `backend/tests/integration/test_phase2b_review_flow.py`
- Modify: `backend/tests/e2e/test_web_run.py`
- Create: `docs/superpowers/acceptance/2026-08-20-phase-2b-review-acceptance.md`

- [ ] **Step 1: Add end-to-end review flow tests**

Cover edit creates version 2; stale edit returns 409; reject evidence affects only linked section; rewrite failure keeps the base version; governance blocks forbidden language; explicit preference adoption creates a preference version; rollback creates a new preference version; approval enables copy but never calls a publishing integration.

- [ ] **Step 2: Run complete validation**

```powershell
$env:TEMP = (Join-Path (Get-Location) '.pytest-temp')
$env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -m pytest backend/tests/unit backend/tests/integration backend/tests/e2e -q -p no:cacheprovider
.\.venv\Scripts\ruff.exe check backend/src backend/tests
Push-Location web
npm.cmd test -- --run
npm.cmd run build
Pop-Location
git diff --check
```

Expected: all backend/frontend tests pass, Ruff is clean, production build succeeds, and no secret or automatic publishing call appears in logs.

- [ ] **Step 3: Record acceptance evidence and commit**

Record command outputs, version IDs, governance results, review duration and known limitations in the acceptance document, then commit the evidence.

```bash
git add backend/tests/integration/test_phase2b_review_flow.py backend/tests/e2e/test_web_run.py docs/superpowers/acceptance/2026-08-20-phase-2b-review-acceptance.md
git commit -m "test: accept phase 2b review flow"
```
