# SectorPulse Phase 1C Repair 设计规格

> 状态：用户已批准设计；等待规格文档复核

## 1. 背景

Phase 1C 已实现 FastAPI、React 工作台、运行历史、SSE 进度、雷达、草稿、证据和审核视图的基础骨架，但当前实现尚不满足可交付条件：运行时依赖被 Git 忽略的测试 Fixture、Live 模型路由仍使用 Fixture 模型名、SSE 生命周期不完整、前端缺少可靠刷新和真实浏览器测试、Web 应用也没有正式启动入口。

本阶段是对 Phase 1C 的收敛修复，不扩大到“获取当前行情与新闻后自动成文”的纵向集成。后者单独作为 Phase 1D 设计和实施。

## 2. 目标与非目标

### 2.1 目标

- 让源码检出和 Wheel 安装环境都能独立启动 Fixture Web 工作台。
- 修复 Live Provider 的预检、模型路由、成本累计和预算门禁。
- 建立可终止、可回放、有界且可清理的 SSE 生命周期。
- 修复历史运行读取、任务完成刷新、错误展示、取消和重试体验。
- 完整展示雷达、草稿、Claim 到新闻来源的证据链和审核报告。
- 建立可提交、可重复的后端、前端和真实浏览器测试体系。
- 提供默认绑定 `127.0.0.1` 的正式 Web 启动命令。

### 2.2 非目标

- 不自动采集当前行情或新闻，不串联 Phase 1A.2 到 Phase 1B。
- 不实现定时调度、失败恢复队列、插件系统或自动发布。
- 不实现多用户、登录、权限和远程公网部署。
- 不改变四级归因标准、确定性门禁和人工发布边界。
- 不引入 Redis、Celery、消息队列或独立任务进程。

## 3. 修复策略

采用“边界整理式修复”，保持 FastAPI、SQLite、React、TypeScript 和 Vite 技术栈，不重写 Phase 1B 管线。

不采用仅在现有 `RunService` 中继续追加条件分支的补丁方式，因为这会延续运行装配、Provider 选择、查询转换、任务生命周期和导出渲染混在同一类中的问题。也不重写整个 Phase 1C，以免破坏已经稳定的领域契约和数据库结构。

## 4. 后端架构

```text
FastAPI API
   |
   +-- RunCommandService
   |     +-- 校验 Phase1BRequest
   |     +-- ProviderPreflight 同步预检
   |     +-- 创建、取消和重试后台任务
   |
   +-- RunQueryService
   |     +-- 运行概览
   |     +-- 雷达与门禁
   |     +-- 草稿版本与导出
   |     +-- Claim、证据、新闻来源与调用审计
   |     +-- 审核报告
   |
   +-- LLMProviderFactory
   |     +-- Fixture Provider
   |     +-- Live OpenAI-compatible Provider
   |     +-- 阶段模型路由与计价
   |
   +-- RunTaskRegistry
   |     +-- 活跃 asyncio Task
   |     +-- 取消和完成清理
   |
   +-- ProgressBus
         +-- 有界事件回放
         +-- 订阅者广播
         +-- 终态标记
         +-- 关闭和清理
```

### 4.1 RunCommandService

负责命令型操作，不承担查询 DTO 拼装：

- 严格校验 `Phase1BRequest`。
- 在写入 `RUNNING` 和创建任务前完成 Provider 预检。
- 为运行生成唯一 `run_id`，统一重绑输入中的上下文和门禁 run ID。
- 启动 Phase 1B 后台任务并注册到 `RunTaskRegistry`。
- 在成功、失败、取消和异常路径统一写入运行终态。
- 保存脱敏输入快照，使用户可基于原输入重试；密钥和完整 Prompt 不得落库。

### 4.2 RunQueryService

只读取 SQLite 已持久化结果，不重新执行领域计算。它输出稳定的 Web DTO，并负责：

- 历史运行与运行详情。
- 雷达卡、确定性门禁原因和支持/反证信息。
- 指定草稿版本、最新草稿、Markdown 和纯文本导出。
- `Claim -> evidence_id -> NewsEvent -> NewsDocument` 的显式关联。
- Prompt 版本、模型、Token、成本和安全错误码等调用审计。
- 审核决策、问题和允许的局部修订范围。

### 4.3 LLMProviderFactory 与预检

Fixture 与 Live 使用统一工厂，但有不同的前置条件：

- Fixture 响应移动到正式运行资源目录，并由 `importlib.resources` 或等价的 package-resource 机制读取。
- 运行时代码不得依赖 `backend/tests`。
- Live 必须同时满足 `.live-llm-consent`、API Key、Base URL、模型和价格配置。
- 缺少任一 Live 条件时，`POST /api/runs` 同步返回 `409`，不写入 `RUNNING`，不触发网络请求，也不回退到 Fixture。
- Agent 不再硬编码 `fixture-high` 等模型名；每个阶段从统一路由解析 `provider` 和 `model`。
- 环境变量指定单模型时，对所有 Live 阶段显式覆盖；配置阶段路由时则按阶段选择模型。审计记录必须保存实际发送的模型名。

### 4.4 成本与预算

- 每次 Agent 调用使用实际模型对应的价格计算成本。
- 管线汇总所有调用成本，并持久化到 `phase1b_runs.total_cost_cny`。
- 每个阶段完成后检查累计成本；超过 `budget_cny_per_run` 时停止后续模型调用并进入 `BUDGET_EXCEEDED`。
- Fixture 成本为零，但仍记录调用阶段、Prompt 版本和模型标识。
- 未配置价格的 Live 模型不得默认为零成本运行，应在预检阶段拒绝或标记为不可计价。

### 4.5 RunTaskRegistry 和 ProgressBus

- 活跃任务只在执行期间保留；`finally` 必须清理已结束任务。
- SSE 订阅前先确认 run 存在，不存在返回 `404`。
- ProgressBus 为每个 run 保存有界事件缓冲和终态。
- 晚订阅者先收到缓冲事件，随后在终态事件后自动关闭。
- 运行中的订阅者收到 `done`、`error` 或 `cancelled` 后关闭。
- 事件缓冲设置数量上限和清理策略，防止长期单用户运行导致无界内存增长。
- 服务重启后不依赖内存事件恢复历史详情；遗留 `RUNNING` 记录转换为明确的中断状态。

## 5. 资源和交付结构

### 5.1 Git 跟踪边界

以下内容必须被 Git 跟踪：

- `backend/tests/` 中的测试代码和测试 Fixture。
- `docs/` 中的规格、计划和验收记录。
- 正式运行 Fixture、Prompt 和数据库迁移。
- 前端源码、测试配置和浏览器 E2E。

以下内容继续忽略：

- `.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`。
- `.test-tmp/`、临时 SQLite、覆盖率报告。
- `node_modules/`、`web/dist/` 和 TypeScript 增量构建缓存。
- `.env*`、API Key、consent 文件和运行数据。

### 5.2 正式资源

运行 Fixture 与测试 Fixture 分离：

- 正式 Fixture 用于本机演示和离线验收，随 Python 包发布。
- 测试 Fixture 用于边界条件、失败路径和小规模断言，保留在测试目录。
- 测试可以使用正式 Fixture 验证交付完整性，但正式代码不能引用测试路径。

前端采用构建时产物策略：开发时由 Vite 代理 API；验收和本机运行时先构建 SPA，再由正式 Web 启动命令托管 `web/dist`。Wheel 是否内嵌 SPA 在实施计划中固定为一种方式并以干净安装测试证明，不允许依赖开发机绝对路径。

## 6. API 契约

保留现有 REST 路径，并补齐：

- `GET /api/providers/status`：返回 Fixture 可用性、Live consent、缺失配置项、预算和安全的模型显示信息，不返回密钥。
- `GET /api/runs/{run_id}/draft/{version}`：读取指定不可变草稿版本。
- `POST /api/runs/{run_id}/retry`：基于已保存的脱敏输入快照创建新 run，不覆盖旧 run。

现有端点继续支持运行列表、详情、雷达、最新草稿、证据、审核、Markdown/纯文本导出、SSE 和取消。

错误语义固定为：

- 请求结构错误：`422`。
- Live 配置或 consent 不满足：`409`。
- run、草稿版本或只读资源不存在：`404`。
- 运行失败：写入安全错误码和脱敏摘要，并通过 SSE 发送 `error`。

## 7. 前端数据流和交互

```text
打开运行详情
   |
   +-- 立即 GET /api/runs/{id}
   |
   +-- status == RUNNING
   |      +-- 建立 SSE
   |      +-- 增量更新阶段进度
   |      +-- 终态后刷新详情和已加载标签
   |
   +-- status != RUNNING
          +-- 不建立 SSE
          +-- 直接读取持久化结果
```

### 7.1 新建运行

- 前端先读取 Provider 状态。
- Fixture 默认可选；Live 未满足前置条件时禁用并显示缺失项。
- 输入 JSON 在客户端做基础格式检查，服务端执行最终领域校验。
- 创建成功后跳转运行详情并订阅进度。

### 7.2 运行详情

- 页面挂载和 `run_id` 变化时立即读取详情。
- 明确展示加载、运行中、成功、失败、取消和中断状态。
- 失败状态展示安全错误摘要和重试按钮。
- 任务结束后刷新已打开标签，避免早期空数据永久停留。

### 7.3 五个视图

- 概览：状态、耗时、成本、Provider、输入摘要、审核结论和阶段进度。
- 雷达：板块、归因等级、置信度、门禁上限、门禁原因、结论、支持证据、反证和不确定性。
- 草稿：标题、导语、正文区块、结论、风险提示、来源清单、指定版本读取、版本比较和复制导出。
- 证据：按板块展示 Claim，再沿 evidence ID 展开新闻事件、来源链接和调用审计。
- 审核：决策、返工轮次、问题级别、问题说明和建议修复范围。

## 8. 正式启动方式

增加 `sector-pulse web` 命令：

- 默认 `host=127.0.0.1`、端口使用明确默认值并允许本机参数覆盖。
- 启动前初始化数据库并检查前端静态资源。
- 静态资源缺失时给出明确构建命令，不静默启动只有 API 的残缺工作台。
- 不默认绑定 `0.0.0.0`，避免无认证服务暴露到局域网或公网。

## 9. 测试策略

### 9.1 Python 单元测试

- 正式 Fixture 可被 package-resource 读取。
- Live preflight 的 consent、环境变量、模型和价格组合。
- 阶段模型路由和实际模型审计。
- 调用成本汇总和预算超限短路。
- ProgressBus 的实时订阅、晚订阅、终态关闭、404 前置条件和有界清理。
- RunTaskRegistry 的完成和取消清理。
- 指定草稿版本和证据链 DTO。

### 9.2 API 集成测试

使用 FastAPI、真实临时 SQLite 和 Fixture Provider 验证：

- 创建运行、SSE 完整顺序和最终状态。
- 运行历史、详情、雷达、草稿版本、证据、审核和导出一致。
- Live 缺配置同步 `409` 且没有网络调用。
- 不存在 run 的 REST/SSE 返回 `404`。
- 取消、失败和重试保留不可变历史。
- App、Service 与 SSE 路由使用同一个 ProgressBus。

### 9.3 React 测试

引入 Vitest、React Testing Library 和 Mock Service Worker 或等价的稳定 API mock：

- 历史运行首次加载。
- 详情页首次加载和终态不连接 SSE。
- 运行中 SSE、完成刷新和错误展示。
- Provider 状态、新建运行和禁用 Live。
- 雷达、完整草稿、证据链和审核视图。

### 9.4 Playwright E2E

启动真实 FastAPI 和构建后的 SPA，以 Fixture 完成：

1. 打开 `127.0.0.1` 工作台。
2. 创建 Fixture 运行。
3. 观察阶段进度和归因计数。
4. 等待可人工审核终态。
5. 查看雷达、草稿、证据和审核。
6. 复制或下载 Markdown/纯文本。
7. 重启服务后重新打开历史运行并确认结果仍可读。

浏览器 E2E 不触发真实行情、真实新闻或真实模型。

## 10. 数据迁移与兼容性

- 优先复用现有 `003/004` 表。
- 为重试保存脱敏输入快照时使用独立迁移，旧记录允许没有快照，因此只能查看、不能重试。
- 现有运行、草稿、审核和调用审计保持可读。
- `run_phase1b_pipeline()` 保持现有签名兼容性，可选 Sink 继续提供空实现。
- CLI 的 Fixture 运行方式保持可用。
- 不删除或覆盖历史草稿版本和旧 run。

## 11. 验收门禁

Phase 1C Repair 只有同时满足以下条件才完成：

1. Git 正常跟踪测试、规格、计划和必要 Fixture。
2. 干净源码检出和干净 Wheel 安装均不依赖测试目录启动 Fixture Web。
3. Fixture Playwright E2E 验证 SSE、雷达、草稿、证据和审核。
4. Live 缺配置同步返回 `409`，并证明没有网络请求。
5. 配置 Live 后，各 Agent 使用配置的实际模型，审计和成本一致。
6. SSE 对不存在 run 返回 `404`，晚订阅回放后自动结束。
7. 历史运行在服务重启后可读取，遗留运行状态不会永久停在 `RUNNING`。
8. Ruff、mypy、后端全量测试、前端测试、Playwright、Python 构建和前端构建全部通过。
9. 真实行情、真实新闻和真实模型分别报告验收状态，不以 Fixture 结果代替。
10. `.gitignore` 仅忽略缓存、构建产物、运行数据和密钥，不忽略测试或项目文档。

## 12. 后续阶段

Phase 1C Repair 验收后，再单独设计 Phase 1D：由一次 Web 手动运行自动锁定 cutoff、采集当时行情和新闻、执行全市场筛选、构建归因上下文、生成并审核一篇通用稿。Phase 1D 不与本修复阶段混合实施。
