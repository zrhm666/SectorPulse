# SectorPulse Phase 1D-1 真实数据采集与验收设计

## 1. 目标

Phase 1D-1 将现有 Fixture 优先的 Web 工作台扩展为可执行 A 股行业板块、概念板块真实数据采集的分析前置链路。该阶段只负责行情、新闻、候选板块、证据包和质量报告，不调用真实 LLM，不生成最终文章，也不自动发布。

验收成功的定义是：用户可以选择盘中或盘后模式启动一次真实数据运行，系统保存可复盘快照，并明确返回 `READY_FOR_ATTRIBUTION`、`DEGRADED` 或 `BLOCKED`，且每个降级和阻塞结论都有确定性原因。

## 2. 范围与非目标

### 范围

- A 股行业板块和概念板块全市场行情扫描。
- 盘中和盘后两种运行模式。
- 市场预候选板块筛选。
- CLS、东方财富、巨潮资讯的两阶段新闻召回。
- 新闻去重、时间门禁、来源分级、实体映射和板块特异性检查。
- 行情快照、新闻文档、新闻事件、板块映射、证据包和质量报告持久化。
- Web API 任务入口、进度事件、运行详情和失败原因。
- Fixture 与真实数据运行严格区分。

### 非目标

- 不调用真实 LLM。
- 不执行新闻驱动归因、文章生成和事实审核。
- 不自动发布到雪球、支付宝或其他平台。
- 不加入多用户、公网认证、插件市场或定时调度。
- 不把研究用途数据源描述成正式商业授权数据。

## 3. 方案选择

采用“双通道、两阶段召回”。

第一阶段用 AKShare 获取行业和概念板块行情，对全市场执行低成本扫描；第二阶段只对预候选板块执行新闻召回。新闻同时走全局热点发现通道和板块关键词精确通道，公告类信息由巨潮资讯补强。

未采用全板块逐一搜索新闻，因为请求量和失败面会随板块数量线性放大；未采用单一新闻源，因为发现型新闻和公告型证据承担不同职责，无法相互替代。

## 4. 架构边界

### Application

- `RealDataRunOrchestrator`：串联运行创建、行情采集、候选筛选、新闻召回、质量评估和终态落库。
- `MarketScanService`：并行获取行业和概念板块行情，并锁定运行截止时间。
- `CandidateRankingService`：按照行情异动、成交活跃度、涨停或领涨特征形成预候选列表。
- `NewsRecallService`：执行全局发现和候选板块关键词检索。
- `EvidenceQualityService`：执行时间、来源、板块特异性、重复和反证门禁。
- `Phase1D1QueryService`：组装只读 Web DTO，不暴露数据源内部对象。

### Ports

- `MarketDataPort`：行业、概念板块行情。
- `SectorConstituentPort`：板块成分股和龙头信息。
- `GlobalNewsDiscoveryPort`：市场热点发现。
- `KeywordNewsSearchPort`：板块关键词新闻搜索。
- `DisclosureSearchPort`：公告和一手来源检索。
- `RealDataRunRepositoryPort`：运行状态和质量摘要。

### Infrastructure

- AKShare 行情适配器。
- AKShare CLS、东方财富、巨潮资讯适配器。
- SQLite 仓储和迁移。
- 后续正式授权数据源只实现相同 Port，不改变 Application 流程。

## 5. 数据流

```text
用户选择 intraday / post_close
  -> 创建 REAL_DATA 运行并同步预检 consent 与配置
  -> 并行抓取行业、概念行情
  -> 校验数量、字段、时间和数据状态
  -> 锁定 cutoff_at
  -> 保存不可变行情快照
  -> 生成最多 30 个市场预候选
  -> 执行全局热点发现
  -> 对预候选执行关键词新闻和公告召回
  -> 去重并排除 cutoff_at 之后的文档
  -> 解析新闻事件并映射板块
  -> 选择最多 12 个最终候选
  -> 生成证据包和质量报告
  -> READY_FOR_ATTRIBUTION / DEGRADED / BLOCKED
```

## 6. 运行模式

### 盘中 `intraday`

- 使用当前可获得行情。
- 默认新闻回溯 6 小时。
- 结果标记为盘中观察，不使用收盘确定性措辞。
- 行情时间不一致时允许降级，但必须保留原因。

### 盘后 `post_close`

- 默认新闻回溯 24 小时。
- 要求行业和概念行情都满足收盘后时间规则。
- 核心行情未锁定时直接 `BLOCKED`。

两种模式都允许用户手动指定执行时间；系统以实际采集时间和锁定截止时间为审计依据。

## 7. 候选排序

第一阶段排名只使用确定性市场字段，不使用 LLM：

- 涨跌幅绝对值。
- 成交额或换手活跃度。
- 上涨、下跌家数及广度。
- 龙头股和拖累股贡献。
- 涨停、异动个股数量。
- 全局新闻命中数量与时效。

字段缺失时按配置降权，不伪造零值。社区讨论热度接口未接入时，明确降级为市场指标与新闻热度。

## 8. 新闻和证据门禁

- 新闻发布时间晚于 `cutoff_at`：排除。
- 来源无法识别或正文、标题均缺失：排除。
- 同一 URL、规范标题或正文指纹重复：合并。
- 仅含宽泛市场词、没有板块或成分股关联：背景信息。
- 巨潮公告可作为 `PRIMARY`；CLS、东方财富默认作为发现型或辅助来源。
- 发现型新闻不能单独升级为“明确驱动”。
- 无可靠新闻时仍保存板块行情，证据包标记 `NO_RELIABLE_EXPLANATION`。
- 反向行业表现、利好不涨、利空不跌等反证必须进入证据包。

## 9. 状态模型

- `PREFLIGHT`：检查 consent、配置和 Provider 注册。
- `FETCHING_MARKET`：抓取行业和概念行情。
- `RANKING_PRE_CANDIDATES`：确定性预候选排序。
- `FETCHING_NEWS`：双通道新闻召回。
- `BUILDING_EVIDENCE`：去重、映射和证据包生成。
- `READY_FOR_ATTRIBUTION`：核心质量通过，可进入 Phase 1D-2。
- `DEGRADED`：可查看但存在明确降级，不自动进入后续归因。
- `BLOCKED`：核心行情或时间门禁失败。
- `FAILED`：程序或 Provider 异常。
- `CANCELLED`：用户取消。

重启后发现遗留的非终态运行时，将其标记为 `INTERRUPTED`，不得自动重复访问外部数据源；用户可手动重试并产生新的 run ID。

## 10. Web API

- `POST /api/data-runs`：创建盘中或盘后真实数据运行。
- `GET /api/data-runs`：运行列表。
- `GET /api/data-runs/{run_id}`：状态和质量摘要。
- `GET /api/data-runs/{run_id}/events`：SSE 进度。
- `GET /api/data-runs/{run_id}/candidates`：候选板块。
- `GET /api/data-runs/{run_id}/evidence`：新闻事件、来源和板块映射。
- `GET /api/data-runs/{run_id}/quality`：行情、新闻和来源质量报告。
- `POST /api/data-runs/{run_id}/cancel`：取消。
- `POST /api/data-runs/{run_id}/retry`：基于模式和参数创建新运行。

真实数据入口必须检查 `.live-data-consent`。缺少 consent、Provider 未注册或配置缺失时同步返回 409，不先写入 `RUNNING`。

## 11. Web 界面

首页新增“盘中分析”和“盘后分析”按钮。用户不输入内部 JSON，只配置：

- 运行模式。
- 新闻回溯小时数。
- 预候选数量。
- 最终候选数量。

运行详情显示行情质量、新闻源状态、候选板块、新闻事件、排除原因和降级原因。Phase 1D-1 不显示“文章已生成”。

## 12. 错误与降级

- 行业或概念核心行情缺失：`BLOCKED`。
- 单个新闻源失败：继续其他来源并记录 `DEGRADED`。
- 全部新闻源失败：保存行情候选，标记 `DEGRADED`，禁止进入 Phase 1D-2。
- 网络超时：按来源配置有限重试，不无限重试。
- 数据解析异常：记录安全错误码，不保存原始敏感响应全文。
- API Key 不适用于当前 AKShare 方案；未来接入授权 Provider 时只从本地环境变量读取。

## 13. 测试与验收

### 离线测试

- Fixture 行情和新闻适配器覆盖盘中、盘后、降级、阻塞和取消。
- 验证 cutoff 之后新闻被排除。
- 验证重复文档合并。
- 验证候选数量上限和行业、概念覆盖。
- 验证单源失败不影响其他来源。
- 验证遗留运行恢复为 `INTERRUPTED`。

### Live 验收

- 必须显式提供 `.live-data-consent` 和 `--run-live`。
- 记录接口耗时、文档数量、事件数量、映射率和错误码。
- 不将 Live 失败回退成 Fixture 成功。
- 验收报告保存来源状态和时间，不保存新闻全文。

### 完成门槛

- 离线全套测试通过。
- 盘中和盘后 Fixture E2E 通过。
- 至少一次真实行情行业、概念双快照成功。
- 至少两个新闻来源返回可审核结果，或明确记录外部阻塞原因。
- Web 可查看质量报告和证据链。

## 14. 后续衔接

Phase 1D-2 只消费 `READY_FOR_ATTRIBUTION` 的运行，将候选、行情快照、证据包和门禁结果转换为现有 `Phase1BRequest`。`DEGRADED` 和 `BLOCKED` 默认不自动生成文章，除非后续增加显式人工批准流程。
