# SectorPulse Stage 0 可靠性与工程底座设计

日期：2026-08-30  
状态：已完成分节讨论，等待书面规格确认  
适用范围：SectorPulse 本地单用户运行时、SQLite/PostgreSQL 双数据库、React 运营后台

## 1. 背景与目标

SectorPulse 已形成行情和新闻采集、候选板块、证据归因、LLM 写作、人工审核及治理闭环。完整复审确认主流程具备良好测试基础，但定时触发、手动计划触发、取消与重启恢复、草稿自动保存、PostgreSQL 桥接及类型门禁仍存在可靠性缺口。

Stage 0 的目标不是增加业务页面，而是让已有能力在正常轮询、进程中断、数据库切换、高负载和失败恢复条件下保持真实、一致、可测试。完成后，系统才进入关注板块、运行对比、新闻证据增强等功能阶段。

## 2. 已确认的约束

1. 继续同时支持 SQLite 和 PostgreSQL。
2. SQLite 用于 Fixture、开发和快速体验；PostgreSQL 用于长期正式运行。
3. 配置 PostgreSQL 后不得静默回退到 SQLite。
4. 不删除、不重建现有用户数据库；迁移只前进。
5. Live 数据和 LLM 始终受 consent 控制，普通测试不得访问外部服务或消耗额度。
6. 不改变已经确认的前端视觉系统和页面信息架构。
7. 不通过 `Any`、大范围 `cast`、忽略规则或单纯延长测试超时伪造质量通过。

## 3. 方案选择

### 3.1 采用方案

采用“同步 Repository Protocol + 异步外部工作流”结构：

- SQLite 仓储保持同步。
- PostgreSQL 使用同步 SQLAlchemy 和 psycopg 驱动。
- FastAPI 路由、行情/新闻 Provider、LLM 和长时间工作流保持异步。
- 数据库调用通过明确的同步 Repository Protocol 暴露，不再由每次调用创建线程和短事件循环。

此方案与现有同步应用服务最匹配，能以有限风险删除 `BlockingAsyncRepository`、`NullPool` 和大量 `object` 类型边界。

### 3.2 未采用方案

- 全异步仓储与应用服务：长期扩展性高，但会同时改写大部分服务、路由和测试，超出本阶段风险预算。
- 保留异步 PostgreSQL 并强化包装器：改动较少，但继续保留线程、事件循环和连接生命周期问题，无法达到 Stage 0 的工程目标。

## 4. 目标架构

### 4.1 存储契约层

按能力拆分 Repository Protocol，而不是创建一个全能仓储：

- `RunRepository`：数据运行、内容运行和状态迁移。
- `ScheduleRepository`：计划、下一触发时间和版本。
- `TaskRepository`：任务、租约、检查点、事件和重试关系。
- `CandidateSelectionRepository`：候选选择版本和确认状态。
- `DraftRepository`：草稿、补丁和版本。
- `EvidenceRepository`：新闻、证据和人工决定。
- `GovernanceRepository`：批准、撤销、导出和审计事件。

协议参数和返回值使用领域模型或明确 DTO。SQLite/PostgreSQL 各自实现协议，并通过同一组契约测试。应用服务只依赖协议，不依赖具体数据库类。

### 4.2 任务协调层

新增 `RunCoordinator` 作为统一命令入口，负责：

1. 校验触发请求和 consent。
2. 通过事务创建 task run、data run 关联和首个任务事件。
3. 把执行交给任务注册表。
4. 接受取消请求并等待执行器落持久化终态。
5. 根据原运行生成有审计关联的新重试运行。

手动计划触发、自动计划触发和其他内部触发都调用此协调器，不再各自拼装任务记录。

### 4.3 调度层

`next_run_at` 是调度事实来源。调度循环读取 `next_run_at <= now` 的启用计划，并通过数据库幂等约束保证每个计划时隙只触发一次。

触发成功后计算下一个符合时区和交易日规则的时间。触发失败只记录该计划的错误事件；调度循环继续处理其他计划。轮询间隔、进程暂停和系统休眠不得导致计划永久跳过。

### 4.4 前端状态层

草稿自动保存提取为独立状态机。每个字段维护：

- 当前本地值；
- 已持久化基线；
- 当前服务端版本；
- `clean/dirty/saving/saved/failed/conflict` 状态；
- 保存中到达的新值和待处理队列。

事件入口同步更新状态机，再触发 React 渲染。失焦、debounce、重试和保存完成都进入同一状态转换，避免 state/ref 观察时序不同。

取消和恢复状态使用后端持久化事实。前端发出取消后显示“正在取消”，轮询到 `CANCELLED` 后才显示完成；进程遗留任务显示 `INTERRUPTED` 并提供重新运行入口。

窄屏侧边栏关闭时使用 `inert` 和可访问隐藏状态；打开时限制焦点范围；关闭后恢复到菜单按钮。

## 5. 任务状态模型

### 5.1 状态流

```text
QUEUED
  -> RUNNING
    -> READY_FOR_HUMAN_REVIEW
    -> DEGRADED
    -> FAILED
    -> CANCELLED
    -> INTERRUPTED

FAILED / CANCELLED / INTERRUPTED
  -> RETRY_WAITING
    -> 新运行
```

`INTERRUPTED` 表示进程退出、租约失效或执行任务丢失，不等同于业务失败。重试默认创建新的运行 ID，并通过 `retry_of_run_id` 保留来源关系。

### 5.2 状态写入规则

- API 只发命令，不提前写最终状态。
- 执行器是 `RUNNING` 之后终态的唯一写入者。
- 取消由执行器捕获 `CancelledError`，在清理后写入 `CANCELLED`。
- 应用启动时运行恢复器：活动任务没有有效执行租约时写入 `INTERRUPTED`。
- 只有安全检查点可进入自动恢复；其他中断任务等待用户重新运行。
- 所有状态变化记录触发来源、旧状态、新状态、安全错误码、尝试次数和时间。
- 日志和数据库不得保存 API Key、数据库密码、完整第三方响应或未经处理的异常正文。

## 6. 数据库迁移设计

### 6.1 新增字段

在新的迁移版本中为任务/运行补充：

- `retry_of_run_id`；
- `cancel_requested_at`；
- `interrupted_reason`；
- `heartbeat_at` 或等价租约字段；
- 调度计划的 `last_triggered_at`；
- 必要的状态和到期查询索引。

实际字段归属以现有 `task_runs`、`real_data_runs` 和 `phase1b_runs` 职责为准，避免在多个表重复维护同一事实。

### 6.2 迁移原则

- 保留现有 001–015 文件不变，新增连续版本。
- SQLite 与 PostgreSQL 使用相同版本号和业务语义。
- 迁移执行前只读检查当前版本和目标版本。
- 迁移失败时终止启动，并输出不包含连接串和密钥的错误信息。
- 提供迁移前备份命令；系统不自动删除或重建数据库。
- 对迁移重复执行、已有数据、空库和中途失败分别测试。

## 7. PostgreSQL 改造

1. 增加 psycopg 同步驱动依赖，SQLAlchemy 使用同步 Engine。
2. 将 PostgreSQL 仓储方法改为与 Repository Protocol 一致的同步方法。
3. 删除 `BlockingAsyncRepository`、`_run_awaitable()`、每调用线程和 `NullPool` 特殊处理。
4. 统一事务边界和连接生命周期，由 Engine 管理连接池。
5. 将 `RuntimeStorageBundle` 的 `object` 字段替换为具体 Protocol。
6. SQLite/PostgreSQL 契约测试验证返回模型、异常、事务、幂等和状态迁移一致性。

本阶段不引入远程数据库管理、读写分离、多租户或高可用集群。

## 8. API 与错误处理

- 保留现有公开路由，避免前端大范围迁移。
- 计划触发接口返回已创建并已交给协调器的任务 ID；不能只返回孤立队列记录。
- 取消接口返回“取消已请求”状态；详情接口提供最终持久化状态。
- 重试响应同时返回新运行 ID 和原运行关系。
- 409 用于状态冲突或缺少确认，404 用于资源不存在，422 用于输入错误，503 用于当前依赖不可用。
- 第三方 Provider、数据库和 LLM 错误转换为稳定错误码；详细堆栈只进入本机日志。
- 调度循环对每个计划单独捕获异常，任何单项失败都不能终止循环。

## 9. 前端修复范围

### 9.1 自动保存

- 快速 change + blur 必须立即提交最新值。
- 保存中继续输入必须在前一次返回后以新版本提交。
- 409 冲突保留本地文本，并提供重新加载和重试选择。
- 页面离开时有未保存内容必须提示。
- 状态提示不只依赖颜色。

### 9.2 运行与调度

- “立即运行”只有在后端真正接受执行后才导航。
- 取消过程区分“正在取消”和“已取消”。
- `INTERRUPTED` 显示原因和重新运行入口。
- 调度页面显示后端计算的下一触发时间和最近触发结果。

### 9.3 无障碍

- 关闭的移动导航不进入焦点和辅助技术树。
- 打开导航和管理抽屉均限制焦点并支持 Escape。
- 减少动态模式只移除装饰性位移/循环动画，保留必要的无位移状态反馈。

## 10. 代码组织

在保持路由兼容的前提下，将 1171 行 `web/app.py` 拆分为：

- 应用工厂和 lifespan；
- operations router；
- data-runs router；
- runs/review router；
- schedules/tasks router；
- shadow/prompt-golden router；
- 静态 SPA 挂载。

拆分只移动依赖和路由职责，不借机改写业务规则。旧 `styles.css` 按使用情况逐步迁移到分层样式，确认无引用后删除。

## 11. 测试与质量门禁

### 11.1 后端

- 定时任务在计划时间后延迟 1、10、30 秒轮询均只触发一次。
- 连续轮询、进程暂停、周末、时区和夏令时边界行为明确。
- 手动触发真正启动 data run 并写入关联事件。
- 取消、超时、崩溃、重启和重试产生正确状态。
- SQLite/PostgreSQL 跑同一组 Repository 契约测试。
- 迁移测试覆盖空库、已有 015 数据库和幂等执行。
- Mypy strict 清零，不增加大范围忽略。

### 11.2 前端

- 默认并行 Vitest 稳定通过，不以单 worker 作为最终门禁。
- 自动保存增加快速失焦、连续输入、并发返回、冲突和离页测试。
- Playwright 对未 mock API、console error、page error 和失败请求默认失败。
- E2E preview/后端进程在 Windows 正常退出。
- 窄屏键盘导航验证关闭侧栏不可聚焦。

### 11.3 综合门禁

交付前必须通过：

1. Ruff；
2. Mypy strict；
3. 后端非 Live 测试；
4. SQLite 契约测试；
5. PostgreSQL 实库契约和迁移测试；
6. Vitest 默认并行；
7. TypeScript/Vite build；
8. Playwright；
9. npm 生产依赖审计；
10. 敏感文件扫描和 `git diff --check`。

Live 测试继续由 consent 和单独命令控制，不计入普通回归。

## 12. 实施阶段

### Phase A：失败复现和契约保护

为调度时间窗口、手动触发、取消落库、启动恢复、自动保存竞态和移动导航建立失败测试。补充 SQLite/PostgreSQL Repository Protocol 契约测试骨架。

### Phase B：任务与调度可靠性

实现 `RunCoordinator`、持久化到期调度、取消确认、中断恢复、重试关系和异常隔离。

### Phase C：双数据库统一

引入同步 PostgreSQL 驱动，类型化 Protocol 和 bundle，迁移 PostgreSQL 仓储，删除异步桥接。

### Phase D：前端可靠性与无障碍

替换自动保存状态机，完善取消/中断文案，修复移动导航焦点和 reduced-motion 行为。

### Phase E：入口拆分与质量门禁

拆分 FastAPI router，清理 legacy CSS，修复测试运行器、依赖告警和全部 Mypy 错误。

### Phase F：完整验收

在 SQLite、PostgreSQL、桌面和窄屏环境执行综合门禁，记录未执行的 Live 边界和最终验收证据。

## 13. 非目标

- 新增关注板块、通知、全文新闻、模型对比或历史复盘。
- 多用户、权限、多租户或公网部署。
- 自动发布、自动交易或投资收益预测。
- 为本阶段重做视觉设计。
- 在普通测试中调用真实数据或真实 LLM。

## 14. 完成定义

Stage 0 完成必须同时满足：定时和手动触发真实可执行；取消和重启后没有虚假活动状态；SQLite/PostgreSQL 行为一致；自动保存无已知竞态；移动导航符合键盘要求；严格类型检查、默认并行测试、构建、端到端和依赖门禁全部通过；现有用户数据通过前进迁移保留。
