# SectorPulse Phase 1C 基础 Web 工作台设计

## 1. 背景与目标

Phase 1B 已实现确定性归因门禁、多 Agent 谨慎归因、选题、成文、审核与局部返工闭环，产物通过 CLI（`phase1b-draft`）在本地 SQLite 中持久化。但用户目前只能通过命令行查看运行结果，无法直观看到重点板块雷达、证据链、草稿和审核报告，也无法从 Web 手动触发一次运行并实时观察进度。

Phase 1C 的目标是交付一个**只读 Web 工作台 + 手动运行**：

- 从 Web 手动触发一次 Phase 1B 归因/成文运行（复用现有管线）；
- 通过 SSE 实时展示阶段级运行进度；
- 展示运行历史列表；
- 以页面形式查看重点板块雷达（分析卡、归因等级、置信度、证据）；
- 查看草稿（标题、正文、来源清单、风险提示、版本只读对比）；
- 查看证据视图（Claim → 证据 → 新闻来源链接、调用审计）；
- 查看审核报告；
- 支持 Markdown / 纯文本复制导出；
- 支持 Fixture 与真实模型两种 Provider（真实模型需显式 consent）。

Phase 1C **不包含**正文编辑、证据决策保存、定时调度和自动发布，这些留给 Phase 2。

## 2. 设计原则

1. 复用 Phase 1B 已冻结的领域契约、持久化和管线，不在 Web 层重建领域逻辑。
2. 进度埋点通过可选回调注入，不改动领域契约；默认空实现保证 CLI 与现有测试零改动。
3. 管线保持"不知道自己正在被 Web 监控"，SSE 只是进度接收方之一。
4. 单进程单体，不引入 Redis / 消息队列 / 子进程（符合主计划约束）。
5. 所有只读查询直接读取 SQLite 已持久化的结构化产物，不做重复计算。
6. API Key 只从环境变量或本机凭据读取，绝不回传前端、不写入日志或数据库。
7. 默认绑定 127.0.0.1，单用户，Phase 1C 不做登录认证。
8. 真实模型调用保持显式 consent 门禁，缺少配置时不触网、不静默回退到 Fixture。
9. 界面为只读工作台，编辑、版本修改与证据决策留给 Phase 2B。

## 3. 总体架构

```text
浏览器 (React SPA, 单页 + 标签)
   │  REST: /api/runs, /api/runs/{id}/radar|draft|evidence|review
   │  SSE:  /api/runs/{id}/events        (进度实时流)
   ▼
FastAPI (异步, 单进程, 绑定 127.0.0.1)
   │
   ├── RunService (应用层)
   │     │  启动后台 asyncio 任务 → run_phase1b_pipeline(...)
   │     │  任务通过 ProgressBus 发阶段事件 → SSE 广播
   │     ▼
   │  Phase 1B 管线 (现有, 加进度埋点, 不改领域契约)
   │     Provider 选择: fixture 默认 / live(需 consent+env)
   │
   └── 读取 SQLite (现有 003 表 + 新增 004 phase1b_runs 表)
         运行历史 / 分析卡 / 草稿版本 / 审核 / 调用审计 / 证据
```

单进程 asyncio 后台任务直接运行现有 `run_phase1b_pipeline`。前端生产构建由 FastAPI 托管静态资源；开发时 Vite dev server 代理 `/api` 到后端。

## 4. 进度事件机制

### 4.1 ProgressSink（管线埋点）

给 `run_phase1b_pipeline` 增加一个可选参数 `progress_sink: ProgressSink`，默认值为 `NoopProgressSink`：

```python
class ProgressSink(Protocol):
    def emit(self, stage: str, detail: dict) -> None: ...

class NoopProgressSink:
    """什么都不做，保证现有调用方/测试零改动。"""
    def emit(self, stage, detail): pass
```

阶段切换点调用 `sink.emit(...)`，例如：

- `phase1b.start`：装载输入上下文、门禁结果；
- `attribution.progress`：detail 含已完成/总数（如 `{"done": 3, "total": 8}`）；
- `attribution.done`：归因完成，detail 含分析卡数量；
- `editorial.done`：选题完成；
- `writing.done`：成文完成；
- `review.done`：审核完成；
- 失败路径：`phase1b.failed`，detail 含错误摘要。

设计要点：

- `emit` 只"通报"阶段事实，不依赖任何 Web 技术，不感知 SSE / 浏览器。
- 默认 `NoopProgressSink` 使 CLI（`phase1b-draft`）与现有测试完全不受影响。
- Web 服务传入一个转发到 `ProgressBus` 的真实现，以后日志、WebSocket、本地通知可各挂一个 sink 复用。

### 4.2 ProgressBus 与 SSE 广播

- `ProgressBus` 是进程内事件总线：以 `run_id` 为 key 维护订阅者集合，`emit` 到的阶段事件广播给该 run 的所有 SSE 订阅者。
- `GET /api/runs/{run_id}/events` 订阅进度。服务端推送：

  - `{"type":"progress","stage":"attribution.progress","detail":{...}}`
  - `{"type":"done","result":{...}}`（结束，含结果摘要）
  - `{"type":"error","message":"..."}`（运行失败）

- 若 run 已结束，订阅时先回放缓冲事件再关闭；run 不存在返回 404。

## 5. 后端接口

### 5.1 REST 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/runs` | 运行历史列表（倒序，含状态/耗时/成本/Provider/草稿引用） |
| `POST` | `/api/runs` | 创建并启动一次手动运行 |
| `GET` | `/api/runs/{run_id}` | 运行概览（状态、耗时、成本、Provider、输入摘要、审核结论） |
| `GET` | `/api/runs/{run_id}/radar` | 重点板块雷达（分析卡 + 归因等级 + 置信度 + 门禁原因） |
| `GET` | `/api/runs/{run_id}/draft` | 草稿（标题/正文/来源清单/风险提示 + 版本列表） |
| `GET` | `/api/runs/{run_id}/draft/{version}` | 指定版本（只读对比用） |
| `GET` | `/api/runs/{run_id}/draft.md` | 原始 Markdown 下载 |
| `GET` | `/api/runs/{run_id}/draft.txt` | 原始纯文本下载 |
| `GET` | `/api/runs/{run_id}/evidence` | 证据视图（Claim → 证据 → 新闻来源链接 + 调用审计） |
| `GET` | `/api/runs/{run_id}/review` | 审核报告（决策、问题区块、允许修订范围） |
| `POST` | `/api/runs/{run_id}/cancel` | 取消运行中任务（轻量） |

### 5.2 手动运行数据流

1. 前端粘贴/上传输入 JSON（服务端用 `Phase1BRequest` 严格校验），选择 Provider（fixture 默认；live 需 `.live-llm-consent` + 环境变量，界面前置展示配置状态与预算）。
2. `POST /api/runs` → 校验通过 → 插入 `phase1b_runs` 行（`RUNNING`）→ 启动 asyncio 后台任务。
3. 任务装配依赖（fixture 或 live Provider、PromptRegistry、Repository）→ 调用 `run_phase1b_pipeline(deps, request, progress_sink=web_sink)`。
4. `web_sink` 把阶段事件转发进 `ProgressBus` → 广播给该 run 的 SSE 订阅者。
5. 结束 → 更新 `phase1b_runs` 行（状态、耗时、成本、draft_id）→ 推 `done`/`error` 事件。

### 5.3 Provider 选择

- **fixture（默认）**：复用 `FixtureLLMProvider` 与默认 fixture 响应文件路径（`backend/tests/fixtures/phase1b/fixture_responses.json`，路径可配置）。无需 API Key，结果可重复。
- **live**：要求存在 `.live-llm-consent` 且环境变量 `SECTOR_PULSE_LLM_API_KEY / BASE_URL / MODEL` 已配置；复用现有 `OpenAICompatibleProvider` 与 `config/llm.yaml` 的模型路由和预算。运行前界面上展示配置状态与单次预算/预估成本。
- 缺少 live 配置时返回 `409` + 明确提示，不静默回退到 fixture。

## 6. 数据模型

### 6.1 新增 phase1b_runs 表（迁移 004）

与 Phase 1A 已有的 `analysis_runs`（数据采集 run 追踪）职责不同，本表用于 Phase 1B 归因/成文运行历史，命名加 `phase1b_` 前缀避免混淆。

```sql
CREATE TABLE phase1b_runs (
  run_id TEXT PRIMARY KEY,
  requested_at TEXT NOT NULL,
  provider TEXT NOT NULL,      -- fixture / live
  status TEXT NOT NULL CHECK (status IN (
    'RUNNING', 'READY_FOR_HUMAN_REVIEW', 'REVISE_REQUIRED',
    'UNREVIEWED', 'BUDGET_EXCEEDED', 'ATTRIBUTION_BLOCKED',
    'DRAFT_GENERATION_FAILED', 'FAILED', 'CANCELLED'
  )),
  elapsed_ms INTEGER,
  total_cost_cny TEXT,
  input_json_hash TEXT,
  draft_id TEXT,
  error_message TEXT,
  finished_at TEXT
);
```

### 6.2 复用已有表

Phase 1B 已建立的表全部复用，不重复建表：

- `attribution_contexts`、`attribution_gate_results`：门禁与上下文
- `sector_analysis_cards`、`claims`：分析卡与 Claim
- `article_outlines`：选题提纲
- `article_drafts`（含版本）：草稿版本
- `review_reports`、`review_issues`：审核报告与问题
- `agent_invocations`：调用审计

## 7. 前端结构与交互

### 7.1 技术形态

- React + TypeScript + Vite 单页应用；`react-router` 提供干净 URL（`/` 列表、`/runs/:runId` 详情）。
- 不引入重型 UI 库/状态库：少量共享组件（Badge、Card、Tab、Table、Spinner）+ 手写 CSS；数据层用简单 `useFetch`/`useRun` hooks。
- 生产构建由 FastAPI 托管静态资源；开发时 Vite 代理 `/api` 到后端。

### 7.2 页面结构

```
Layout: 左侧运行列表栏 + 主区
 ├─ /                    RunListPage：运行历史（状态徽章、耗时、成本、Provider），「新建运行」按钮
 └─ /runs/:runId         RunDetailPage：页内标签
      ├─ 概览   状态 / 耗时 / 成本 / Provider / 输入摘要 / 审核结论；运行中显示 SSE 阶段进度
      ├─ 雷达   板块卡片（归因等级徽章、置信度、一句话结论、支持/反证、门禁原因）
      ├─ 草稿   标题、导语、正文区块、来源清单、风险提示；版本下拉切换 + 两版本只读对比；复制 MD/纯文本
      ├─ 证据   按板块：Claim → 证据 → 新闻来源（带链接）；调用审计表（Prompt 版本、Token、成本）
      └─ 审核   决策（PASS/REVISE/BLOCK）、问题列表、允许修订范围
```

### 7.3 关键交互

1. **新建运行**（modal）：粘贴或上传输入 JSON → 选择 Provider（fixture 默认；live 未满足 consent 时显示「未配置」提示）→ 启动 → 跳转详情页并自动打开 SSE。
2. **实时进度**：EventSource 订阅 `/api/runs/{id}/events`；运行中概览页显示「数据装载 → 板块归因 N/M → 选题 → 成文 → 审核」阶段进度条，每阶段事件到达即更新。
3. **完成/失败**：SSE `done` 后自动刷新各 tab 数据并切到概览；`error`/阻断时显示原因与「重试」入口。
4. **复制导出**：草稿页按钮把 Markdown/纯文本复制到剪贴板；也提供 `/api/runs/{run_id}/draft.md`（或 `.txt`）原始下载。
5. **版本对比**：草稿 tab 版本下拉，选两个版本做简单只读对比（正文区块两侧并排、差异高亮）。

## 8. 错误处理

- 输入 JSON 校验失败 → `422` + 具体原因。
- live 但缺 consent/环境变量 → `409` + 明确提示，不静默回退。
- 运行中的失败/阻断 → 写入 `phase1b_runs.status` + `error_message`，SSE 推 `error`，前端展示「重试」。
- 只读端点读取不存在的数据 → 404 + 明确原因。
- SSE 订阅一个不存在/已清理的 run → 404。

## 9. 测试策略

### 9.1 后端

- 单元：`RunService`（运行生命周期、Provider 选择校验、phase1b_runs 仓库 CRUD）、`ProgressBus`/SSE 事件格式化、输入 JSON 校验。
- 集成：FastAPI TestClient + 临时 SQLite，fixture Provider 走完整 HTTP 链路——`POST /api/runs` → 收集 SSE 阶段事件 → 各只读端点返回正确数据。
- 进度埋点回归：不传 sink 时行为与现在完全一致；传真 sink 时按顺序收到「装载 → 归因 N/M → 选题 → 成文 → 审核」事件。现有 Phase 1B 测试保持零改动。
- 迁移：004 phase1b_runs 表迁移与 CRUD 测试。
- live：仅在显式 `.live-llm-consent` 下测试，缺失时跳过（沿用 Phase 1B 门禁，不触网）。

### 9.2 前端

- Vitest + React Testing Library：核心组件冒烟测试（运行列表、详情标签、新建运行弹窗、SSE hook——用 mock EventSource）。
- 一条 Playwright 冒烟 E2E（可选）：fixture 新建运行 → 看到进度 → 草稿可见。

### 9.3 验证门禁

- 后端：`ruff` + `mypy` + `pytest` + `uv build`。
- 前端：`tsc --noEmit` + `vitest run` + `vite build`。

## 10. 完成定义

Phase 1C 只有在以下条件全部满足时才视为实现完成：

1. Web 手动运行 fixture 任务可端到端完成，SSE 按顺序展示全部阶段进度；
2. 运行历史、概览、雷达、草稿、证据、审核各视图数据与 SQLite 持久化一致；
3. 草稿支持 Markdown/纯文本复制与原始下载；
4. live Provider 未配置时明确拒绝且不触网，配置后显式 consent 才可运行；
5. 进度埋点不影响 CLI 与现有 Phase 1B 测试；
6. 全量后端（ruff/mypy/pytest/build）与前端（tsc/vitest/build）验证通过。

## 11. 本阶段范围外

Phase 1C 不实现：

- 正文编辑、证据决策保存、全文改写（Phase 2B）；
- 定时调度、失败自动恢复（Phase 2A）；
- 自动发布、多平台适配；
- 登录认证、多用户、权限、计费；
- 插件系统；
- Redis/消息队列/PostgreSQL/容器化；
- 写作偏好学习。

这些能力分别留给 Phase 2 与后续阶段。Phase 1C 的交付边界是"只读工作台 + 手动运行 + 实时进度 + 全部只读视图"。
