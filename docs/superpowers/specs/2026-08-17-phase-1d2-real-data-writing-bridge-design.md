# SectorPulse Phase 1D-2 真实数据到文章生成桥接设计

## 1. 目标

Phase 1D-2 将 Phase 1D-1 已持久化的真实行情、候选板块、新闻事件和证据包转换为现有 `Phase1BRequest`，调用真实的第三方 OpenAI 兼容 LLM，生成一篇可人工审核的文章。

本阶段不增加定时调度、失败自动恢复、全文编辑、证据人工裁决或自动发布；这些能力仍属于 Phase 2。

## 2. 核心决策

采用持久化桥接：真实采集、行情快照、新闻证据、归因上下文、模型调用记录和文章草稿共享同一个 `run_id`。Phase 1D-2 从数据库重建写作输入，不依赖 Phase 1D-1 的进程内对象。

选择该方案的原因：

- 服务重启后仍可从 `READY_FOR_ATTRIBUTION` 运行继续生成文章；
- 不复制行情和新闻数据，不产生两个可能不一致的数据真相；
- Web、数据库和审计日志使用同一个运行身份；
- 现有 Phase 1B pipeline 可以直接复用。

## 3. 运行身份修复

当前 `RealDataRun` 与 `run_phase1a2_probe()` 内部创建的 `AnalysisRun` 使用不同 UUID，导致真实运行记录与快照、证据包无法稳定关联。Phase 1D-2 实施前先修复此边界：

- `Phase1A2Request` 接受可选 `run_id`；
- Phase 1D-1 Web 编排器必须将 `RealDataRun.run_id` 传给 Phase 1A.2；
- `AnalysisRun`、`sector_snapshots`、`evidence_packs`、`news_retrieval_links`、Phase 1B 表和文章表全部使用该 ID；
- 已存在的旧运行不进行隐式迁移；只有修复后创建的运行可进入 Phase 1D-2。

## 4. 写作门禁

新增应用层桥接服务，在任何数据库读取或 LLM 调用前验证：

- 运行存在；
- 状态严格等于 `READY_FOR_ATTRIBUTION`；
- cutoff 已锁定；
- 行业和概念快照均存在；
- 至少存在三个可构建归因上下文的候选板块；
- 每个候选存在对应 `EvidencePack`。

`DEGRADED`、`BLOCKED`、`FAILED`、`CANCELLED`、`INTERRUPTED` 不允许调用 LLM。门禁失败返回稳定的应用错误码，API Key、第三方响应正文和内部异常不进入错误响应。

## 5. 持久化输入重建

桥接服务按 `run_id` 加载：

- `RealDataRun` 与候选板块；
- 行业和概念 `SectorUniverseSnapshot`；
- `EvidencePack`；
- `NewsEvent`、关联的 `NewsDocument`；
- `SectorEventLink`。

对每个候选：

1. 从两类快照中定位 `SectorSnapshot`；
2. 调用现有 `build_attribution_context()` 构建只读归因上下文；
3. 调用现有 `evaluate_attribution_gate()` 计算最大归因等级；
4. 汇总为 `Phase1BRequest(run_id, requested_at, contexts, gates)`；
5. 调用现有 `run_phase1b_pipeline()`。

桥接层不改写原始新闻、不提升归因等级，也不自行生成文章。

## 6. 候选持久化修复

Phase 1D-1 当前生成最终候选和证据包，但真实运行仓储没有稳定保存对应 `RealDataCandidate`。采集完成后必须将最终候选写入 `real_data_candidates`，保留：

- sector ID 与种类；
- 排名；
- 选择分数；
- 选择原因。

Phase 1D-2 只消费这些已持久化候选，不重新运行候选排序。

## 7. 配置设计

项目根目录 `.env` 保存部署相关和敏感配置：

```dotenv
SECTOR_PULSE_DATABASE_PATH=data/sector-pulse.db
SECTOR_PULSE_LLM_PROVIDER=openai-compatible
SECTOR_PULSE_LLM_BASE_URL=
SECTOR_PULSE_LLM_API_KEY=
SECTOR_PULSE_LLM_MODEL=
SECTOR_PULSE_LLM_TIMEOUT_SECONDS=60
SECTOR_PULSE_LLM_BUDGET_CNY=2.00
SECTOR_PULSE_LLM_MAX_ATTRIBUTION_CONCURRENCY=4
SECTOR_PULSE_LLM_MAX_REVISION_ROUNDS=2
```

配置优先级固定为：操作系统环境变量 > 项目根目录 `.env` > `config/llm.yaml` 默认值。

实现使用 `python-dotenv`，启动 Web/CLI 时从项目根目录加载 `.env`，并设置 `override=False`。`.env` 已被 Git 忽略；新增 `.env.example`，只包含空值或无密钥示例。

五个阶段 `attribution`、`editorial`、`writing`、`review`、`revision` 第一版共用 `SECTOR_PULSE_LLM_MODEL`。YAML 继续保存路由结构和价格表；环境变量覆盖 provider、model、预算、并发和超时。

## 8. 真实 LLM Provider

复用现有 `OpenAICompatibleProvider`，请求目标为：

```text
{SECTOR_PULSE_LLM_BASE_URL}/chat/completions
```

Provider 必须：

- 使用 Bearer API Key；
- 按阶段传入统一环境模型名；
- 保留现有结构化 JSON 校验；
- 将 timeout、网络失败、限流、HTTP 拒绝和 JSON 无效转换为稳定错误码；
- 不记录 Authorization header 或响应原文；
- 遵守单次运行预算和最大归因并发。

真实 LLM 调用仍要求项目根目录存在 `.live-llm-consent`，防止普通开发测试意外消耗额度。

## 9. Web API 与状态

新增面向真实数据运行的生成命令：

```text
POST /api/data-runs/{run_id}/generate
```

行为：

- 校验运行门禁；
- 创建或复用同 `run_id` 的 Phase 1B 执行记录；
- 异步执行桥接与 Phase 1B pipeline；
- 返回 `202 Accepted` 和 `run_id`；
- 现有文章运行详情接口继续读取 Phase 1B 结果。

重复请求采用幂等语义：若运行已经处于执行中或已经产生可审核草稿，不重复调用 LLM，而是返回当前状态。

## 10. 前端边界

真实数据运行详情页在状态为 `READY_FOR_ATTRIBUTION` 时显示“生成分析稿”操作。其他状态显示不可生成原因。生成后沿用现有 Phase 1B 运行详情页展示归因卡片、提纲、草稿、审核结果和成本。

Phase 1D-2 不提供正文编辑或自动发布。

## 11. 安全与错误处理

- API Key 只存在于环境和进程内存；
- `.env`、请求 Authorization header、第三方响应原文不落库；
- 数据库只保存模型名、阶段、用量、估算成本和稳定错误码；
- 缺少配置时在调用 LLM 前返回 `LLM_CONFIG_MISSING`；
- 缺少 consent 时返回 `LIVE_LLM_CONSENT_REQUIRED`；
- 非 `READY_FOR_ATTRIBUTION` 返回 `REAL_DATA_RUN_NOT_READY`；
- 数据关联不完整返回 `REAL_DATA_BRIDGE_INCOMPLETE`；
- Provider 失败沿用现有 `LLM_TIMEOUT`、`LLM_NETWORK_ERROR`、`LLM_RATE_LIMITED` 等错误码。

## 12. 测试与验收

测试分为三层：

1. 单元测试：运行身份传递、候选持久化、桥接输入构建、门禁、配置优先级和密钥不泄露；
2. 集成测试：使用本地假的 OpenAI 兼容 HTTP 服务，验证 `READY_FOR_ATTRIBUTION → Phase1BRequest → draft → review`；
3. 显式真实验收：要求 `.live-data-consent`、`.live-llm-consent` 和 `--run-live-llm`，调用配置的第三方服务生成一篇文章。

完成标准：

- 新创建的真实数据运行全链路使用一个 `run_id`；
- 非就绪运行不会产生任何 LLM 请求；
- 就绪运行可以从数据库重建至少三个上下文；
- 第三方兼容服务完成归因、编辑、写作和审核；
- 草稿、审核、调用审计和成本可从现有 API 查询；
- 单元测试、集成测试、Ruff 和前端测试通过；
- 真实 LLM 验收输出一篇可人工审核文章，并报告实际 Provider、模型、成本与耗时。

## 13. 非目标

- 定时调度和交易日自动运行；
- 任务级断点恢复与分布式队列；
- 本地行情缓存兜底；
- 正文编辑、证据人工裁决和局部重写 UI；
- 自动发布或推送；
- 为不同写作阶段配置不同模型。
