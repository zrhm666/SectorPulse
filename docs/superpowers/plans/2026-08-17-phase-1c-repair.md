# SectorPulse Phase 1C Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Phase 1C 的交付、Live 模型、运行生命周期和 Web 交互问题，使干净检出环境可启动、可测试、可审计地完成一次 Fixture Web 运行。

**Architecture:** 保留 Phase 1B 领域管线，拆分 Provider 工厂、命令服务、查询服务、任务注册表和有界进度总线。正式 Fixture 作为 Python package resource 交付；FastAPI 负责 REST/SSE 和静态 SPA，React 依据持久化状态决定是否订阅 SSE。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、SQLite、Typer、React 18、TypeScript、Vite、Vitest、React Testing Library、MSW、Playwright。

## Global Constraints

- 市场范围固定为 A 股行业板块和概念板块。
- 不改变 `NO_RELIABLE_EXPLANATION < MARKET_ASSOCIATION < POSSIBLE_CATALYST < EXPLICIT_DRIVER` 四级归因契约。
- 不接入自动发布、定时调度、插件、多用户或公网认证。
- Live 模型必须同时满足显式 consent、环境配置、模型路由和可计价条件；失败不得回退 Fixture。
- API Key、完整 Prompt 和未脱敏输入不得写日志、数据库或返回前端。
- 默认只绑定 `127.0.0.1`。
- 关键类、状态转换、边界转换和异常路径添加中文注释。
- 每个任务先写失败测试，再写最小实现；不得用 Fixture 成功冒充真实网络验收。
- 不修改与本修复无关的 Phase 0、Phase 1A 或 Phase 1B 领域行为。

---

## File Structure

```text
backend/src/sector_pulse/
  resources/phase1b/fixture_responses.json  # 正式离线运行资源
  infrastructure/llm/provider_factory.py    # Provider 预检、阶段路由和实例创建
  application/run_commands.py               # 创建、取消、重试和终态转换
  application/run_queries.py                # 只读 Web DTO
  application/task_registry.py               # 活跃 asyncio Task 生命周期
  web/progress_bus.py                        # 有界回放和终态关闭
  web/app.py                                 # REST/SSE/静态资源装配
  web/server.py                              # 127.0.0.1 启动入口
  storage/migrations/005_phase1c_repair.sql  # 脱敏输入快照和中断状态
web/src/
  api.ts                                     # 类型化 API 客户端
  useRunDetail.ts                            # 详情、SSE 和刷新协调
  pages/...                                  # 完整五视图
web/tests/                                   # Vitest/RTL
web/e2e/                                     # Playwright 浏览器测试
```

### Task 1: 恢复交付资产并迁移正式 Fixture

**Files:**
- Modify: `.gitignore`
- Create: `backend/src/sector_pulse/resources/__init__.py`
- Create: `backend/src/sector_pulse/resources/phase1b/fixture_responses.json`
- Create: `backend/src/sector_pulse/infrastructure/llm/fixture_resources.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Modify: `pyproject.toml`
- Test: `backend/tests/unit/infrastructure/test_fixture_resources.py`
- Test: `backend/tests/test_package_smoke.py`

**Interfaces:**
- Produces: `load_default_fixture_responses() -> dict[str, object]`
- Consumes: `FixtureLLMProvider(responses: Mapping[str, object])`

- [ ] **Step 1: 写失败测试，证明正式资源不依赖测试目录**

```python
def test_default_fixture_is_loaded_from_package() -> None:
    responses = load_default_fixture_responses()
    assert {"article-outline", "article-draft", "review-report"} <= responses.keys()

def test_create_app_does_not_reference_backend_tests(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(database_path=tmp_path / "app.db")
    assert app.title == "SectorPulse Web"
```

- [ ] **Step 2: 运行测试并确认因资源加载函数不存在或测试路径缺失而失败**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/unit/infrastructure/test_fixture_resources.py backend/tests/test_package_smoke.py -v`

Expected: FAIL，且失败原因与 package resource 未实现有关。

- [ ] **Step 3: 移动正式 Fixture 并实现资源加载器**

```python
from importlib.resources import files
import json

def load_default_fixture_responses() -> dict[str, object]:
    resource = files("sector_pulse.resources").joinpath("phase1b/fixture_responses.json")
    raw = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("default fixture responses must be an object")
    return raw
```

将 `app.py` 中 `Path("backend/tests/fixtures/...")` 替换为该函数；在 Hatch 构建配置中显式包含 `resources/**/*.json`。

- [ ] **Step 4: 只删除 `.gitignore` 中精确的 `backend/tests` 和 `docs` 两行**

不得重排或重写其他规则；同时增加 `web/tsconfig.tsbuildinfo` 和 `.tmp/` 等纯生成物规则。

- [ ] **Step 5: 验证源码与 Wheel 都能加载正式 Fixture**

Run: `$env:UV_CACHE_DIR='.uv-cache'; uv build`

Run: `tar -tf dist/sector_pulse-0.1.0.tar.gz | rg "resources/phase1b/fixture_responses.json"`

Expected: 测试 PASS，构建包中存在正式 Fixture；`git check-ignore backend/tests/conftest.py docs/superpowers/specs/2026-08-17-phase-1c-repair-design.md` 均返回非零。

- [ ] **Step 6: 提交资产边界修复**

```powershell
git add .gitignore pyproject.toml backend/src/sector_pulse/resources backend/src/sector_pulse/infrastructure/llm/fixture_resources.py backend/src/sector_pulse/web/app.py backend/tests docs
git commit -m "fix: restore tracked tests and runtime fixtures"
```

### Task 2: 统一阶段模型路由、计价和预算门禁

**Files:**
- Create: `backend/src/sector_pulse/infrastructure/llm/provider_factory.py`
- Modify: `backend/src/sector_pulse/application/attribution_agents.py`
- Modify: `backend/src/sector_pulse/application/editorial_agents.py`
- Modify: `backend/src/sector_pulse/application/phase1b_pipeline.py`
- Modify: `backend/src/sector_pulse/config/llm_config.py`
- Modify: `backend/src/sector_pulse/web/live_provider.py`
- Test: `backend/tests/unit/infrastructure/test_provider_factory.py`
- Test: `backend/tests/integration/test_phase1b_budget.py`

**Interfaces:**
- Produces: `ProviderPreflightResult(available: bool, missing: tuple[str, ...], stage_models: Mapping[str, str])`
- Produces: `LLMProviderFactory.preflight(provider: str) -> ProviderPreflightResult`
- Produces: `LLMProviderFactory.build(provider: str, run_id: UUID) -> LLMProvider`
- Produces: `LLMRuntimeConfig.route_for(stage: str, provider_override: str | None = None) -> LLMRoute`

- [ ] **Step 1: 写失败测试覆盖真实模型名、未知价格和预算超限**

```python
def test_live_route_uses_configured_model(monkeypatch) -> None:
    monkeypatch.setenv("SECTOR_PULSE_LLM_MODEL", "gpt-4o-mini")
    result = factory().preflight("live")
    assert set(result.stage_models.values()) == {"gpt-4o-mini"}

def test_live_model_without_price_is_unavailable() -> None:
    assert "pricing" in factory_without_price().preflight("live").missing

async def test_pipeline_stops_before_next_call_when_budget_is_exceeded() -> None:
    result = await run_with_costs("1.20", "1.10", budget="2.00")
    assert result.status == "BUDGET_EXCEEDED"
    assert provider_call_count(result) == 2
    assert result.total_cost_cny.amount == Decimal("2.30")
```

- [ ] **Step 2: 运行测试并确认当前硬编码 Fixture 模型和零成本行为失败**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/unit/infrastructure/test_provider_factory.py backend/tests/integration/test_phase1b_budget.py -v`

- [ ] **Step 3: 将所有 Agent 的 `LLMRequest.model` 改为显式 `model` 参数**

```python
async def run_attribution_agent(..., model: str, ...) -> SectorAnalysisCard:
    request = LLMRequest(model=model, ...)
```

选题、写作、审核和修订函数使用同一模式；调用方从 `config.route_for(stage)` 传入实际模型。

- [ ] **Step 4: 实现 Provider 预检和实际路由**

预检必须一次性检查 consent、Base URL、API Key、模型和价格；返回缺失字段名，不返回字段值。删除 `_model` 丢弃行为。

- [ ] **Step 5: 在管线累计每次 invocation 成本并执行阶段后预算门禁**

```python
total_cost = MoneyCny(amount=sum((i.estimated_cost_cny.amount for i in invocations), Decimal("0")))
if total_cost.amount > deps.config.budget_cny_per_run:
    return Phase1BRunResult(status="BUDGET_EXCEEDED", total_cost_cny=total_cost, ...)
```

- [ ] **Step 6: 回归测试和提交**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/unit/application backend/tests/unit/infrastructure backend/tests/integration/test_phase1b_pipeline.py backend/tests/integration/test_phase1b_budget.py -q`

```powershell
git add backend/src/sector_pulse backend/tests config/llm.yaml
git commit -m "fix: route live models and enforce budget"
```

### Task 3: 拆分命令、查询与活跃任务生命周期

**Files:**
- Create: `backend/src/sector_pulse/application/task_registry.py`
- Create: `backend/src/sector_pulse/application/run_commands.py`
- Create: `backend/src/sector_pulse/application/run_queries.py`
- Modify: `backend/src/sector_pulse/web/run_service.py`
- Test: `backend/tests/unit/application/test_task_registry.py`
- Test: `backend/tests/unit/application/test_run_commands.py`
- Test: `backend/tests/unit/application/test_run_queries.py`

**Interfaces:**
- Produces: `RunTaskRegistry.start(run_id: UUID, coroutine: Coroutine[Any, Any, None]) -> None`
- Produces: `RunTaskRegistry.cancel(run_id: UUID) -> bool`
- Produces: `RunCommandService.create(input_json: dict[str, Any], provider: str) -> UUID`
- Produces: `RunCommandService.retry(run_id: UUID) -> UUID`
- Produces: `RunQueryService.get_evidence(run_id: UUID) -> EvidenceView`

- [ ] **Step 1: 写失败测试证明预检早于插入、任务完成后清理**

```python
def test_unavailable_live_does_not_insert_run() -> None:
    with pytest.raises(ProviderUnavailable):
        commands.create(valid_input(), "live")
    assert runs_repo.list_runs() == ()

async def test_registry_removes_completed_task() -> None:
    registry.start(RUN_ID, noop())
    await asyncio.sleep(0)
    assert not registry.contains(RUN_ID)
```

- [ ] **Step 2: 写查询测试验证 Claim 到新闻来源的显式关联**

```python
def test_evidence_view_links_claim_event_and_document() -> None:
    view = queries.get_evidence(RUN_ID)
    claim = view.sectors[0].claims[0]
    assert claim.evidence[0].event_id == "event-1"
    assert claim.evidence[0].documents[0].citation_url.startswith("https://")
```

- [ ] **Step 3: 实现小型服务并把旧 `RunService` 降为兼容门面**

命令服务只处理状态变化；查询服务只组 DTO；任务注册表在 done callback 和取消路径清理。旧公开方法暂时委派给新服务，避免一次性破坏 API 测试。

- [ ] **Step 4: 运行测试、确认旧 CLI 和 API 契约不变并提交**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/unit/application backend/tests/unit/web backend/tests/integration/test_phase1b_cli.py -q`

```powershell
git add backend/src/sector_pulse/application backend/src/sector_pulse/web/run_service.py backend/tests
git commit -m "refactor: separate web run commands and queries"
```

### Task 4: 修复 ProgressBus、SSE 终态和资源上限

**Files:**
- Modify: `backend/src/sector_pulse/web/progress_bus.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Test: `backend/tests/unit/web/test_progress_bus.py`
- Test: `backend/tests/integration/test_web_sse.py`

**Interfaces:**
- Produces: `ProgressBus(max_events_per_run: int, max_terminal_runs: int)`
- Produces: `ProgressBus.subscribe(run_id: UUID) -> AsyncIterator[ProgressEvent]`
- Produces: `ProgressBus.finish(run_id: UUID, terminal_event: ProgressEvent) -> None`

- [ ] **Step 1: 写失败测试覆盖晚订阅关闭、404 和有界淘汰**

```python
async def test_late_subscriber_replays_and_stops() -> None:
    bus.emit(RUN_ID, progress("phase1b.start"))
    bus.finish(RUN_ID, done("READY_FOR_HUMAN_REVIEW"))
    assert [e async for e in bus.subscribe(RUN_ID)][-1]["type"] == "done"

def test_unknown_run_sse_returns_404(client) -> None:
    assert client.get(f"/api/runs/{uuid4()}/events").status_code == 404
```

- [ ] **Step 2: 实现每 run 有界 deque、terminal 集合和统一 `finish`**

`finish` 必须先写终态、广播终态、发送关闭哨兵；晚订阅检测终态后回放并立即返回。淘汰只能删除已终止 run 的内存事件，不删除 SQLite 数据。

- [ ] **Step 3: 确保 App、CommandService 和 SSE 路由注入同一个 Bus**

删除测试 override 下 App 自建 Bus 与 Service 内 Bus 不一致的路径，改为显式 `AppDependencies`。

- [ ] **Step 4: 验证事件严格顺序并提交**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/unit/web/test_progress_bus.py backend/tests/integration/test_web_sse.py -v`

```powershell
git add backend/src/sector_pulse/web backend/tests
git commit -m "fix: bound and terminate sse progress streams"
```

### Task 5: 保存脱敏输入快照、恢复中断状态并支持重试

**Files:**
- Create: `backend/src/sector_pulse/storage/migrations/005_phase1c_repair.sql`
- Modify: `backend/src/sector_pulse/storage/phase1b_runs_repository.py`
- Modify: `backend/src/sector_pulse/storage/sqlite.py`
- Modify: `backend/src/sector_pulse/application/run_commands.py`
- Test: `backend/tests/unit/storage/test_phase1c_repair_schema.py`
- Test: `backend/tests/integration/test_run_retry_recovery.py`

**Interfaces:**
- Produces: `Phase1BRunRow.input_payload_json: str | None`
- Produces: `SQLitePhase1BRunsRepository.mark_interrupted_runs(now: datetime) -> int`
- Consumes: `RunCommandService.retry(run_id: UUID) -> UUID`

- [ ] **Step 1: 写失败测试验证旧记录兼容、脱敏快照和恢复语义**

```python
def test_startup_marks_orphan_running_as_interrupted(repo) -> None:
    repo.insert(running_row())
    assert repo.mark_interrupted_runs(NOW) == 1
    assert repo.get_run(RUN_ID).status == "INTERRUPTED"

def test_retry_creates_new_run_without_overwriting_source(commands) -> None:
    new_id = commands.retry(FAILED_RUN_ID)
    assert new_id != FAILED_RUN_ID
    assert repo.get_run(FAILED_RUN_ID).status == "FAILED"
```

- [ ] **Step 2: 新增迁移字段与 `INTERRUPTED` 状态，更新状态约束**

SQLite 迁移不得破坏旧数据；如需重建带 CHECK 的表，必须在事务中复制全部列并验证行数一致。

- [ ] **Step 3: 在写入前对输入执行白名单序列化**

只保存 `Phase1BRequest` 领域字段；显式拒绝键名包含 `api_key`、`authorization`、`secret`、`token` 的未知数据。

- [ ] **Step 4: 在 FastAPI lifespan 启动时恢复遗留运行并提交**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage backend/tests/integration/test_run_retry_recovery.py -q`

```powershell
git add backend/src/sector_pulse/storage backend/src/sector_pulse/application/run_commands.py backend/tests
git commit -m "feat: persist safe retry inputs and recover interrupted runs"
```

### Task 6: 补齐 API 契约和正式 Web 启动命令

**Files:**
- Modify: `backend/src/sector_pulse/web/schemas.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Create: `backend/src/sector_pulse/web/server.py`
- Modify: `backend/src/sector_pulse/cli.py`
- Test: `backend/tests/integration/test_web_api.py`
- Test: `backend/tests/integration/test_web_server_command.py`

**Interfaces:**
- Produces: `GET /api/providers/status`
- Produces: `GET /api/runs/{run_id}/draft/{version}`
- Produces: `POST /api/runs/{run_id}/retry`
- Produces: CLI `sector-pulse web --host 127.0.0.1 --port 8000`

- [ ] **Step 1: 写失败 API 测试**

```python
def test_live_preflight_returns_409_without_inserting(client, repo) -> None:
    response = client.post("/api/runs", json={"provider": "live", "input_json": valid_input()})
    assert response.status_code == 409
    assert repo.list_runs() == ()

def test_get_exact_draft_version(client) -> None:
    response = client.get(f"/api/runs/{RUN_ID}/draft/1")
    assert response.status_code == 200
    assert response.json()["version"] == 1
```

- [ ] **Step 2: 实现 Provider 状态、指定版本和重试端点**

Provider 状态只返回 `available`、`missing`、预算和模型显示名；禁止序列化 Key 或环境变量值。

- [ ] **Step 3: 实现 Typer `web` 命令和静态资源前置检查**

```python
@app.command("web")
def web(host: str = "127.0.0.1", port: int = 8000, static_dir: Path = Path("web/dist")) -> None:
    if host != "127.0.0.1":
        raise typer.BadParameter("Phase 1C 仅允许绑定 127.0.0.1")
    run_web_server(host=host, port=port, static_dir=static_dir)
```

静态目录缺少 `index.html` 时退出并提示 `cd web; npm.cmd run build`。

- [ ] **Step 4: 验证 API、CLI 帮助和静态 fallback 后提交**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_web_api.py backend/tests/integration/test_web_server_command.py -q`

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m sector_pulse.cli web --help`

```powershell
git add backend/src/sector_pulse/web backend/src/sector_pulse/cli.py backend/tests
git commit -m "feat: complete phase1c api and web command"
```

### Task 7: 修复前端运行状态与五视图数据完整性

**Files:**
- Modify: `web/src/api.ts`
- Create: `web/src/useRunDetail.ts`
- Modify: `web/src/useRuns.ts`
- Modify: `web/src/components/NewRunDialog.tsx`
- Modify: `web/src/pages/RunDetailPage.tsx`
- Modify: `web/src/pages/tabs/OverviewTab.tsx`
- Modify: `web/src/pages/tabs/RadarTab.tsx`
- Modify: `web/src/pages/tabs/DraftTab.tsx`
- Modify: `web/src/pages/tabs/EvidenceTab.tsx`
- Modify: `web/src/pages/tabs/ReviewTab.tsx`

**Interfaces:**
- Produces: `useRunDetail(runId: string): RunDetailState`
- Produces: `fetchProviderStatus(): Promise<ProviderStatus>`
- Produces: `fetchDraftVersion(runId: string, version: number): Promise<DraftVersion>`

- [ ] **Step 1: 先在 Task 8 的 Vitest 基础设施中写组件失败测试，或最少用 TypeScript 编译锁定类型**

历史详情测试必须断言组件挂载后立即调用 `GET /runs/{id}`，终态不得建立 EventSource，运行中终态事件必须刷新已加载标签。

- [ ] **Step 2: 将 `unknown[]` API 类型替换为明确 DTO**

类型必须覆盖 `ClaimEvidenceView`、`DraftVersion`、`RadarCard`、`ReviewIssue` 和 `ProviderStatus`，不允许页面继续使用强制 `as` 转换逃避契约。

- [ ] **Step 3: 实现详情状态协调 Hook**

```typescript
useEffect(() => {
  void refreshRun()
}, [runId, refreshRun])

useEffect(() => {
  if (run?.status !== 'RUNNING') return
  return subscribeRun(runId, event => {
    if (isTerminal(event)) void refreshAllLoadedQueries()
  })
}, [runId, run?.status])
```

- [ ] **Step 4: 完整渲染五个视图**

草稿必须显示导语、结论、风险提示和来源；证据必须按 Claim 展开事件与来源；雷达显示门禁原因和支持证据；错误状态提供重试；所有异步视图具有 loading/error/empty 三态。

- [ ] **Step 5: 运行 TypeScript 构建**

Run: `cd web; npm.cmd run build`

Expected: `tsc -b` 与 Vite build 均成功，无 `unknown[]` 强制转换警告。

### Task 8: 建立前端组件测试和 SSE Hook 测试

**Files:**
- Modify: `web/package.json`
- Create: `web/vitest.config.ts`
- Create: `web/tests/setup.ts`
- Create: `web/tests/RunDetailPage.test.tsx`
- Create: `web/tests/NewRunDialog.test.tsx`
- Create: `web/tests/EvidenceTab.test.tsx`
- Create: `web/tests/DraftTab.test.tsx`
- Create: `web/tests/useRunDetail.test.tsx`

**Interfaces:**
- Produces: npm script `test:unit`
- Consumes: Task 7 的类型化 API 与 `useRunDetail`

- [ ] **Step 1: 安装并固定 Vitest、RTL、user-event、jsdom 和 MSW 依赖**

Run: `cd web; npm.cmd install --save-dev vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom msw`

- [ ] **Step 2: 写失败测试覆盖关键用户行为**

```typescript
it('loads a completed historical run without opening SSE', async () => {
  render(<RunDetailPage />, { wrapper: routerFor('/runs/run-1') })
  expect(await screen.findByText('READY_FOR_HUMAN_REVIEW')).toBeVisible()
  expect(MockEventSource.instances).toHaveLength(0)
})

it('renders claim to source linkage', async () => {
  render(<EvidenceTab runId="run-1" />)
  expect(await screen.findByText('政策事实')).toBeVisible()
  expect(screen.getByRole('link', { name: '公告原文' })).toHaveAttribute('href', 'https://example.test/a')
})
```

- [ ] **Step 3: 实现测试辅助设施，禁止真实网络**

MSW 的 `onUnhandledRequest` 设置为 `error`；Mock EventSource 必须支持 message、error 和 close 断言。

- [ ] **Step 4: 运行组件测试与前端构建并提交 Task 7/8**

Run: `cd web; npm.cmd run test:unit -- --run`

Run: `cd web; npm.cmd run build`

```powershell
git add web
git commit -m "test: cover phase1c frontend state and views"
```

### Task 9: Playwright 浏览器 E2E 与干净检出验收

**Files:**
- Modify: `web/package.json`
- Create: `web/playwright.config.ts`
- Create: `web/e2e/fixture-run.spec.ts`
- Create: `scripts/verify-phase1c-clean.ps1`
- Create: `docs/phase1c/README.md`
- Create: `docs/phase1c/latest-fixture-validation.md`

**Interfaces:**
- Produces: npm script `test:e2e`
- Produces: `scripts/verify-phase1c-clean.ps1`，只在临时目录中构建和测试，不改变当前分支

- [ ] **Step 1: 安装 Playwright 并配置两个本地 Web Server**

FastAPI 使用 `sector-pulse web --host 127.0.0.1 --port 8000`；浏览器访问同一地址的已构建 SPA。测试只使用 Fixture Provider。

- [ ] **Step 2: 写真实浏览器失败测试**

```typescript
test('fixture run reaches reviewable draft with evidence', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '新建运行' }).click()
  await page.getByLabel('输入 JSON').setInputFiles('web/e2e/fixtures/phase1b-input.json')
  await page.getByRole('button', { name: '启动' }).click()
  await expect(page.getByText('READY_FOR_HUMAN_REVIEW')).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: '证据' }).click()
  await expect(page.getByRole('link', { name: /来源/ })).toBeVisible()
  await page.getByRole('button', { name: '草稿' }).click()
  await expect(page.getByText(/风险提示/)).toBeVisible()
})
```

- [ ] **Step 3: 增加服务重启后的历史读取用例**

E2E 保存 run ID，重启 Web Server 后直接打开 `/runs/{id}`，断言不依赖 SSE 仍显示草稿和审核结果。

- [ ] **Step 4: 编写干净检出验证脚本**

脚本必须使用 `git archive HEAD` 解压到系统临时目录，创建隔离虚拟环境，构建 Python 包和前端，运行 Fixture E2E；不得切换当前工作树 HEAD。脚本结束后只清理自己创建且已经校验位于系统临时目录的目录。

- [ ] **Step 5: 运行最终验证门禁**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests -q --basetemp '.test-tmp/phase1c-final'`

Expected: 全部离线测试 PASS；Live 测试仅因缺少显式开关而 SKIP。

Run: `.\.venv\Scripts\python.exe -m ruff check backend/src backend/tests`

Run: `.\.venv\Scripts\python.exe -m mypy backend/src`

Run: `$env:UV_CACHE_DIR='.uv-cache'; uv build`

Run: `cd web; npm.cmd run test:unit -- --run`

Run: `cd web; npm.cmd run build`

Run: `cd web; npm.cmd run test:e2e`

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify-phase1c-clean.ps1`

- [ ] **Step 6: 写入事实化验收报告**

报告分别记录 Fixture、真实行情、真实新闻和真实模型状态。没有在本轮执行的 Live 验收必须写 `NOT_RUN`，不得写“完成”。

- [ ] **Step 7: 最终代码审查和提交**

使用 `superpowers:requesting-code-review` 审查从 Phase 1C Repair 起点到当前 HEAD 的完整 diff，修复所有 Critical 和 Important 项后再提交：

```powershell
git add web scripts docs/phase1c backend pyproject.toml config
git commit -m "test: validate phase1c repair end to end"
```

## Final Acceptance Checklist

- [ ] `backend/tests`、`docs` 和正式 Fixture 均被 Git 跟踪。
- [ ] 源码和 Wheel 环境不依赖测试目录启动 Fixture Web。
- [ ] Live 缺配置同步返回 `409`，无运行记录、无网络请求。
- [ ] Live Agent 使用真实模型路由，调用审计、成本和预算状态一致。
- [ ] SSE 未知 run 返回 `404`；晚订阅回放并自动结束；内存有界。
- [ ] 历史运行重启后可读，遗留 `RUNNING` 转换为 `INTERRUPTED`。
- [ ] 五个 Web 视图展示规格要求的完整数据和错误状态。
- [ ] 后端、前端、浏览器 E2E、构建和干净检出验证全部通过。
- [ ] Live 行情、新闻和模型状态单独报告，未运行时明确写 `NOT_RUN`。
