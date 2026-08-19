# Phase 2A：可靠任务与调度设计

## 1. 目标与范围

Phase 2A 将 Phase 1D 的“手动启动一次、进程内执行一次”扩展为可恢复的任务系统：用户可以配置盘中、盘后或自定义时间计划，系统能够持久化每次运行的状态，在服务重启后恢复未完成任务，并对可重试故障执行有限重试和明确降级。

本阶段采用应用内嵌调度器，SQLite 作为计划、任务、阶段尝试和检查点的持久化存储。手动触发仍是第一等入口，现有 Phase 1D 的 Live 数据与真实 LLM 流程继续复用。文章仍停留在人工审核、复制和导出边界，不实现自动发布。

## 2. 非目标

- 不引入 Redis、Celery、消息队列或分布式锁服务。
- 不实现多实例同时消费同一个任务；SQLite 单进程部署是本阶段运行边界。
- 不实现全文编辑、证据人工裁决、局部重写和版本治理，这些属于 Phase 2B。
- 不把缓存当作真实数据的无条件替代；Provider 降级必须带质量状态和审计原因。
- 不自动登录或调用任何内容平台发布接口。

## 3. 设计原则

1. **计划与执行分离**：调度器只决定何时创建任务，执行器负责推进任务状态机。
2. **阶段结果不可变**：每个成功阶段写入带输入指纹和版本的检查点；重试创建新的阶段尝试，不覆盖原记录。
3. **幂等优先**：重复点击、重复调度和服务重启不能产生重复的有效运行或重复 LLM 扣费。
4. **失败语义明确**：网络/限流/临时 Provider 故障与数据完整性、配置和合规失败分别处理，不能把失败伪装成“暂无可靠解释”。
5. **可观测但不泄密**：日志、SSE 和 API 只返回阶段、状态、Provider、安全错误码和摘要，不返回 API Key、完整 Prompt 或敏感响应正文。

## 4. 组件边界

### 4.1 `ScheduleService`

负责计划的创建、修改、启停、下一次触发时间计算和交易日规则校验。它不执行数据采集，也不直接调用 LLM。

计划字段至少包括：`schedule_id`、名称、运行模式（`intraday`/`post_close`/`manual`）、本地时间、时区、交易日规则、输入参数模板、启用状态、配置版本和更新时间。

### 4.2 `EmbeddedScheduler`

作为 FastAPI 应用生命周期内的单进程后台任务运行。服务启动时读取启用计划，按短周期唤醒并为到期计划创建 `TaskRun`；服务关闭时停止新的调度，不强制中断已经落库的阶段尝试。

调度器必须使用数据库唯一约束完成竞争保护，而不是依赖内存标志。时间计算统一转换为 UTC 存储，展示时按计划时区转换。

### 4.3 `TaskRunService`

负责手动触发、计划触发、查询、取消、重试和恢复入口。它复用现有 `RunService` 的 Phase 1D 桥接能力，但将当前“一次性后台 task”包装为持久化状态机。

### 4.4 `RunExecutor`

按固定阶段推进任务：

```text
QUEUED
  -> FETCHING_MARKET
  -> FETCHING_NEWS
  -> QUALITY_CHECKED
  -> ATTRIBUTING
  -> WRITING
  -> READY_FOR_HUMAN_REVIEW
```

任何阶段都可能进入 `RETRY_WAITING`、`DEGRADED` 或 `FAILED`。已经成功的阶段从检查点读取，不重复调用 Provider 或 LLM；进入 `READY_FOR_HUMAN_REVIEW` 后任务视为终态，不由调度器自动重新生成。

## 5. 持久化模型

新增 SQLite migration，建议包含以下表：

### `schedules`

保存计划定义和版本。`schedule_id` 为主键；`enabled`、`timezone`、`mode`、`schedule_spec_json`、`input_template_json`、`version` 和审计时间为必需字段。

### `task_runs`

保存每次运行的业务状态：`run_id`、可选 `schedule_id`、计划触发时间、实际开始/结束时间、当前状态、`input_fingerprint`、`run_cutoff_at`、错误码、降级原因和最终产物引用。

唯一键为：

```text
schedule_id + trading_date + planned_slot + input_fingerprint
```

手动运行没有 `schedule_id`，但仍使用客户端幂等键或服务端生成的输入指纹避免同一请求重复提交。

### `run_stage_attempts`

每条记录表示一个阶段的一次尝试：`run_id`、阶段名、attempt 序号、状态、输入/输出指纹、开始/结束时间、重试原因、错误码、Provider、耗时和检查点引用。失败记录不可更新为成功，只能新增下一次 attempt。

### `run_checkpoints`

保存阶段成功后的不可变产物。字段包括 `checkpoint_id`、`run_id`、阶段名、schema/version、输入指纹、产物 JSON 或文件引用、产物 hash、创建时间。读取时必须校验 hash、schema 版本和对应的输入指纹。

### `task_events`

保存状态迁移和人工操作审计：来源（scheduler/manual/recovery）、旧状态、新状态、操作者/请求幂等键、时间和安全摘要。它用于恢复诊断，不作为业务状态的唯一来源。

## 6. 状态机与恢复

状态迁移必须由一个集中式 transition 函数校验，禁止 Web handler 直接修改任意状态。状态迁移示例：

| 当前状态 | 允许迁移 |
|---|---|
| `QUEUED` | `FETCHING_MARKET`, `CANCELLED` |
| 采集/质量/归因/写作阶段 | `RETRY_WAITING`, 下一阶段, `DEGRADED`, `FAILED`, `CANCELLED` |
| `RETRY_WAITING` | 原阶段, `FAILED`, `CANCELLED` |
| `DEGRADED` | 下一阶段, `READY_FOR_HUMAN_REVIEW`, `FAILED` |
| `READY_FOR_HUMAN_REVIEW` | 终态 |
| `FAILED` | 仅显式“重试运行”创建新 attempt 或新 run |

服务启动恢复时：

1. 查询非终态 `TaskRun` 和没有结束时间的阶段尝试。
2. 将超过租约时间的执行标记为可恢复，而不是直接标记失败。
3. 校验最近一个成功检查点；校验通过则从下一阶段继续，校验失败则从该阶段重新执行。
4. 恢复动作写入 `task_events`，并保持原阶段 attempt 历史。

单进程租约使用 `worker_id`、`lease_until` 和数据库条件更新实现；服务关闭不删除租约，启动恢复依靠租约过期判断。

## 7. 幂等、重试与降级

### 7.1 幂等

- 创建任务使用数据库唯一键和 `INSERT ... ON CONFLICT` 语义；冲突时返回已有 `run_id`。
- 每个阶段的执行前检查同一 `run_id + stage + input_fingerprint + implementation_version` 是否已有有效检查点。
- LLM 调用沿用现有 invocation 记录；同一阶段恢复时优先读取已完成 invocation，不重复扣费。
- 取消、重试和恢复接口都要求请求幂等键，重复请求返回原操作结果。

### 7.2 重试分类

可重试：连接断开、超时、HTTP 429、临时 5xx、Provider 明确的临时不可用。采用指数退避并设置最大 attempt 数和总 deadline。

不可重试：配置缺失、结构化输出持续不合法、数据完整性失败、cutoff 违规、来源约束失败、预算不足和人工审核拒绝。

每次重试记录 `retry_after`、退避秒数和错误摘要；不使用无限重试。达到上限后进入 `FAILED` 或允许继续的 `DEGRADED`，具体由阶段质量策略决定。

### 7.3 降级

降级必须显式写入质量报告和 `downgrade_reasons`。核心行情不可用时不生成可发布草稿；非核心新闻源部分失败时可以继续，但文章必须保留实际来源和质量标记。`NO_RELIABLE_EXPLANATION` 仍然是合法业务结果，不能用模型猜测补齐证据。

## 8. API 与前端契约

新增或扩展以下接口：

```text
GET    /api/schedules
POST   /api/schedules
PATCH  /api/schedules/{schedule_id}
POST   /api/schedules/{schedule_id}/enable
POST   /api/schedules/{schedule_id}/disable
POST   /api/schedules/{schedule_id}/trigger

GET    /api/task-runs/{run_id}
POST   /api/task-runs/{run_id}/cancel
POST   /api/task-runs/{run_id}/retry
POST   /api/task-runs/{run_id}/resume
GET    /api/task-runs/{run_id}/stages
GET    /api/task-runs/{run_id}/events
```

现有 `/api/runs/{run_id}` 和 `/api/data-runs/{run_id}` 保持兼容，新增字段只允许向后兼容扩展。所有命令接口返回 `run_id`、当前状态、幂等结果标识和安全错误码；轮询与 SSE 的事件格式统一为 `run_id`、阶段、状态、进度、Provider、错误码和时间。

前端第一版只需要计划列表、启停、下一次触发时间、任务状态、阶段进度、重试/恢复按钮和降级原因展示；不在 Phase 2A 引入文章编辑器。

## 9. 配置

重要配置通过 `.env` 或现有配置层读取，并提供安全默认值：

```text
SECTOR_PULSE_SCHEDULER_ENABLED
SECTOR_PULSE_SCHEDULER_POLL_SECONDS
SECTOR_PULSE_TASK_LEASE_SECONDS
SECTOR_PULSE_TASK_MAX_ATTEMPTS
SECTOR_PULSE_TASK_DEADLINE_SECONDS
SECTOR_PULSE_TASK_RETRY_BACKOFF_SECONDS
```

配置解析必须在启动时校验；无效配置阻止调度器启动，但不影响只读 API 读取已有历史任务。

## 10. 测试与验收

单元测试覆盖：时间/时区与交易日计算、幂等键、状态迁移、重试分类、退避、检查点 hash/schema 校验和配置解析。

集成测试覆盖：SQLite migration、重复计划触发、重复手动提交、阶段成功后恢复、租约过期恢复、失败 attempt 不被覆盖、核心行情失败阻断写作、非核心新闻降级和旧 Phase 1D API 兼容。

端到端验收至少包括：

1. 创建一个盘后计划，触发一次并生成 `READY_FOR_HUMAN_REVIEW`。
2. 在新闻采集或归因阶段强制终止进程，重启服务后从最后检查点继续。
3. 同一计划同一交易日重复触发，只有一个有效 `TaskRun`。
4. 模拟 429/超时，验证有限重试、退避和最终安全状态。
5. 模拟一个新闻 Provider 失败，验证质量降级可见且来源不被模型伪造。
6. 运行现有 Phase 1D 单元、集成和真实数据验收，确认手动流程没有回归。

Phase 2A 进入持续验收前，必须满足总路线要求：Phase 1 连续 5 个交易日通过，任务状态、恢复记录和质量对账可追溯。

## 11. 实施顺序

1. 增加 migration、领域状态和仓储接口；先完成状态迁移与幂等约束。
2. 将现有 `RunService` 的执行逻辑抽出为 `RunExecutor`，保持旧 API 适配层。
3. 实现检查点、阶段 attempt、租约和恢复流程。
4. 实现 `ScheduleService` 与 `EmbeddedScheduler`，接入 FastAPI lifespan。
5. 扩展 API、SSE 和前端计划/任务状态视图。
6. 按单元、集成、端到端和连续交易日验收顺序验证。

## 12. 成功标准

Phase 2A 完成的判据是：计划和手动任务都能持久化；重复提交幂等；服务重启能恢复；阶段重试不重复成功阶段；失败/降级原因可查询；旧 Phase 1D 手动流程继续通过；没有自动发布行为；并满足连续 5 个交易日的稳定性验收前置条件。
