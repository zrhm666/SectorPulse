# SectorPulse 运行对比设计

日期：2026-09-07。代码核对基线：本地 `main / bf8d953`。

状态：设计稿已形成，功能尚未实现、尚未验收。本次授权是先写设计和实施计划；详细方案交付后再进入实现。按用户偏好使用当前会话连续执行，不使用子代理。

关联：[实施计划](../plans/2026-09-07-run-comparison.md) · [项目进度](../../PROJECT_STATUS.md) · [项目视觉规范](../../design/sectorpulse-reference-ui-system.md)。这是功能增强路线图 Stage 1 中的一个小阶段，不代表整个 Stage 1 已启动或完成。

## 1. 目标与范围

选择两次已结束的数据运行，以 A 为基准、B 为对照，回答三个问题：哪些候选板块不同，已保存行情相差多少，各自留存了哪些新闻与板块证据关联。

首版不重新采集、不调用 LLM、不生成分析稿、不修改候选选择、不增加数据库迁移，不实现关注列表、自动通知、全文抓取、稿件版本对比或交易功能。

### 全局约束

- 仅查询已持久化数据；不调用行情、新闻或 LLM 上游，不写入业务数据。
- 同时支持 SQLite 和原生 PostgreSQL；Docker 不是前置条件。
- 沿用 Python >=3.12、React 18、TypeScript、FastAPI 及当前锁定依赖；不增加运行时依赖。
- 沿用现有 AppShell、统一导航和 `web/src/styles/tokens.css`；不另建主题或侧边栏。
- 缺失或不可比的值使用 null 和原因；不得替换为零、正常或已完成。
- 新闻文字是当前保存的元数据，不是历史正文快照；不输出历史正文差异。
- 测试使用临时 SQLite 或经核实的独立 PostgreSQL 测试库，禁止使用业务库写入测试数据。
- 当前会话执行，不使用子代理；未获授权不推送远端，不恢复影子测试。

### 默认选择与假设

首版只允许相同 `RealDataRun.provider`（fixture/live）、相同 `request.mode`（intraday/post_close）的不同运行。跨来源或跨场景比较暂不提供开关。此项是推荐默认值，已向用户提出问题、尚未收到单独选项回复，不记作已确认选择。

只能选择数据采集状态 `is_terminal=True` 的运行，包括 READY_FOR_ATTRIBUTION、DEGRADED、BLOCKED、FAILED、CANCELLED、INTERRUPTED。**终态不等于成功，也不要求内容生成已完成。** 失败运行可以展示仍然保存的部分数据；没有快照的类别显示不可比较。

## 2. 代码证据与关键限制

| 已有能力 | 实际入口 | 对本设计的约束 |
| --- | --- | --- |
| 数据运行、状态与候选 | `domain/real_data_run.py`、`storage/real_data_run_repository.py` 及 PostgreSQL 对应实现 | `get_run()` 不带候选；必须独立调用 `get_candidates()`；历史列表目前默认仅 50 条 |
| 每次运行的行情快照 | `domain/market.py`、`storage/market_snapshot_repository.py` | 按 run_id、sector_kind 保存；包含来源、分类版本、观测时间和实际字段声明 |
| 候选评分 | `application/candidate_selection.py` | 组内标准化后合并排序；不能解释为跨运行可直接比较的绝对强度 |
| 新闻采集成员记录 | `NewsRetrievalRepositoryPort.list_query_documents()` | 可以比较留存的 document_id 集合；旧运行可能没有成员记录 |
| 板块—事件关系 | `NewsRetrievalRepositoryPort.list_links()` | 关系带 run_id 和 sector_kind，可直接核对两次运行中保存的关联 |
| 新闻与事件元数据 | `storage/news_repository.py` | document、event 是共享记录，后续保存会更新标题、摘要及事件成员；不是不可变历史正文 |
| 前端工作台 | `DataRunPage.tsx`、`data-run/*` | 已有数据详情，但不能把其兜底补齐后的结果直接当历史差异输入 |

特别注意：`SectorSnapshot.breadth_ratio` 在上涨数、下跌数总和为 0 时返回 0.5；这是模型兜底，不是观测值。比较层应根据实际字段和分母自行判断。

实施核对补充（2026-09-07）：现有 `real_data_candidates` 的主键为 `(run_id, sector_id)`，没有包含 kind，因此同次运行的跨类型同码候选存在原表限制。本功能仍按 `(kind, id)` 对比已经保存的记录，测试纯规则及跨运行不串类型；不在只读功能中隐式引入迁移。新闻成员与板块事件关联存在删除级联，删除历史不能从当前表还原，首版只核对当前留存关系。新闻元数据更新在 PostgreSQL 的同 ID 去重条件已修复，与 SQLite 对齐。前端验收使用隔离 Fixture 和只读 GET，不把示例数据冒充 Live 验收。

文中 `domain/`、`application/`、`storage/` 均相对于 `backend/src/sector_pulse/`。

## 3. 方案选择

| 方案 | 优点 | 代价与结论 |
| --- | --- | --- |
| A：后端只读对比查询，复用已有仓储 | 两种数据库共享规则，缺失值、来源和集合差异语义一致 | 增加小型查询模块及接口；推荐 |
| B：前端拼接现有多个工作台接口 | 后端改动较少 | 默认 50 条列表、分页截断、新闻兜底与前端重复计算容易产生错误差异；不采用 |
| C：新建不可变历史新闻档案与对比报告系统 | 可以进一步支持审计和未来文本差异 | 需要新增采集、版本存储和迁移；历史原文无法凭空补齐；作为独立后续课题 |

首版采用 A。保持现有采集、写作、重试、候选人工选择流程不变。

## 4. 可比较性与差异规则

### 4.1 运行与分类

1. 两个 UUID 必须存在、不同、均为数据运行终态；provider 和 mode 必须相同，否则拒绝对比。
2. 行业、概念分别检查快照 `(provider_id, classification_version)` 是否相同且非空。相同才可把 `(sector_kind, provider_sector_id)` 作为跨运行身份。不得用名称匹配，不得忽略 kind。
3. 某类缺少快照时该类为 UNAVAILABLE；来源或分类版本不同为 INCOMPATIBLE。该类不计算匹配或差异，不把同码板块硬配对；仍展示两侧来源说明和原运行入口。
4. `source_version` 不同、lookback_hours 不同、两类候选上限不同、质量降级、缺少 cutoff 均显式提示。source_version 不同暂允许查看保留数据，不断言采集方法完全一致。
5. A、B 按用户选择的方向排列，不自动按时间交换。若 B 的 cutoff 早于 A，说明“对照时间早于基准”，不得用“最新”命名 B。

### 4.2 候选与行情

首版以两次运行**系统候选集合的并集**为范围，不把全市场所有板块铺进对比页。人工确认的写作板块子集不替代系统候选排名。当前上限通常每次 12 个，但读取实际记录，不硬编码丢弃历史行。

- 对每个兼容类别，候选键去重合并；非候选侧仍可从该侧行情快照取得数值。
- 候选关系：BOTH、ONLY_BASE、ONLY_COMPARE，展示为“两次均入选 / 仅基准入选 / 仅对照入选”。没有入选不代表板块不存在或退市。
- 排名变化 = A.rank − B.rank，正值“上升 n 位”，负值“下降 n 位”；一侧未入选则 null。不把单侧入选虚构为从第 0 名上升。
- 候选分数仅并列展示 A、B 原值，并提示“各次运行内部相对分”；不提供分数差和强弱结论。
- 行情字段首版比较 pct_change、turnover_rate、advancers、decliners；分别保留 name、leader_name 供上下文阅读。更多指标不在首版默认表格铺开。
- 涨跌幅差、换手率差 = B − A，单位为**百分点**；涨跌家数差 = B − A，单位为家。后端 Decimal 运算，API 数值以十进制字符串返回，不使用二进制浮点计算差值。
- 字段需在快照 available_fields 中声明且值非 null，才视为已知；available_fields 为空的历史记录保守按“字段口径未知”处理。0 本身是合法已知值。
- 只要某一侧未知，差值为 null。缺少板块行与缺少字段分别说明。
- 行情变化方向不是建议、好坏或收益预测；使用数值、符号和文字，不用绿代表更好、红代表更差。
- 排序固定：先有 B 排名的候选按 B.rank 升序，再按 A.rank，最后按 kind、id；筛选“行业/概念/全部”和“所有/两次均入选/仅基准/仅对照”只改变显示，不改变摘要统计口径。

### 4.3 新闻记录

比较的是每次运行中 `list_query_documents()` 留存的 document_id 集合。重复 query 命中同一新闻只计一次；**不得从当前共享事件的 document_ids 推导过去采集成员**。

- `lineage=RECORDED` 表示该运行有成员记录，不代表完整抓取所有新闻；`lineage=UNVERIFIABLE` 表示没有可核验成员记录，不能推断当时新闻数为 0。
- 两侧均为 RECORDED 才输出集合“共有 / 仅基准留存 / 仅对照留存”。任何一侧 UNVERIFIABLE，差异统计为 null，新闻差异页显示 unavailable，不把有记录的一侧全部算作新增或消失。
- 每侧的 `recorded_count` 始终表示实际成员去重数；为 0 时文案“未留存成员记录”，不写“没有新闻”。
- 差异名单分页前先对 ID 集合运算；统计不受当前页和元数据是否存在影响。
- 当前元数据丢失的新闻仍保留 ID 和成员关系，标题显示“新闻元数据不可用”，不可静默丢行。
- 详情展示现存标题、来源、发布时间、摘要和安全原文链接，统一标注“当前保存的新闻元数据，非历史正文快照”。不请求正文，不做版本差异，不渲染新闻为 HTML。
- 仅允许 http/https 原文链接，外链使用 `rel="noopener noreferrer"`；无合法地址不生成空按钮。
- 初版按 document_id 稳定排序，不用可变标题或更新时间决定分页；后续可独立增加排序需求。

### 4.4 板块证据

使用运行保存的 `SectorEventLink`，以 `(sector_kind, sector_id, event_id)` 去重。只比较兼容类别、候选并集内的关系；一侧候选未入选，但已留存同一板块的关系，仍可显示。

每条关系并列保留双方 relation_type、mapping_confidence、mapping_reason、rule_version。该功能对比“留存关系是否存在及原始说明”，不宣称证据增强、因果成立、新闻原文变化。事件标题仅作当前元数据辅助说明；丢失标题不丢失关系。

证据关系为空只表述“无留存关联”，不表述“现实中无证据”。若分类不可比，该类显示不可比较，不计算只存在于一侧的关系。

## 5. 页面与交互

页面路径：`/runs/compare?base=<uuid>&compare=<uuid>&tab=sectors`。tab 为 sectors/news/evidence，未指定时为 sectors。`/runs` 菜单持续高亮，不添加新的侧边栏入口。

入口：运行历史页增加次操作“运行对比”；数据运行详情在数据终态时增加“以此为基准对比”，预填 base。未终态详情不显示这个操作，不影响现有轮询和生成稿件按钮。

```text
┌─现有侧栏─┬────────────────────────────────────────────────────┐
│ 分析运行 │ 运行对比                  返回运行历史              │
│  高亮    │ 比较已保存记录，不重新采集数据                      │
│          │ [基准 A：日期 / 场景 / 状态] ⇄ [对照 B：同口径运行] │
│          │ [选择运行]                     [选择运行] [开始对比]│
│          │ 来源、截点、新闻窗口和可比性提示                    │
│          │ 共同候选 n │ 仅基准 n │ 仅对照 n │ 不可比类别 n    │
│          │ [候选与行情] [新闻记录] [板块证据]                  │
│          │ 板块       基准 A          对照 B          差异     │
│          │ ────────── 对齐的行级对照，不并排两个长页面 ─────── │
│          │ 展开行：补充行情 / 分数 / 当前元数据                │
└──────────┴────────────────────────────────────────────────────┘
```

### 视觉与布局

- 使用 compact 页面密度，白色表面、浅蓝灰背景、蓝色操作、细边框；复用 PageHeader、Panel、SummaryStrip、StatusBadge、InlineAlert。
- 选择区是一个整体面板内的 A/B 两列，不给两侧各堆一串卡片。摘要用一条 SummaryStrip；主体使用一张对齐表格。
- 桌面继承当前侧栏 232px、顶栏 68px；页面内容独立滚动，导航不随内容长表滚动。不修改全站外壳尺寸。
- 页面主体不做独立定高三栏和多重滚动。默认表格展示名称、候选排名 A/B/变化、涨跌幅 A/B/差；换手率、家数、名称变化、相对分在行内详情展开。
- 低于 960px，A/B 选择器纵向排列；低于 720px，结果改成逐板块 A/B 对照块，不压缩字体、不让整页横向滚动。中等宽度表格可局部横滚。
- 点击/触控目标桌面至少 40px、窄屏至少 44px，保持可见 focus；差异符号有文字解释，数字等宽对齐。
- 原位展开新闻摘要和辅助字段，使用 button + aria-expanded/aria-controls；首版不复制现有抽屉来制造新的焦点陷阱。

### 选择、请求与错误

- 选择器为原生 dialog 中的分页运行列表，每页 20 条，可按 provider、mode 筛选。选定 A 后，B 列表限制同 provider、mode；运行显示完整时间、短 ID、状态、来源及场景，完整 ID 可见于详情。
- 列表按 requested_at DESC、run_id DESC；可翻到 50 条以外。先选 B 也允许，之后另一侧按已选项约束。更换已选项导致另一侧不兼容时清空另一侧并明确提示。
- A/B 相同、缺一侧时禁用“开始对比”，并显示具体原因。交换按钮交换已选两侧；两侧齐全后才启用。
- 开始对比后提交 URL 参数；直接打开完整 URL 自动加载。交换已提交的 A/B 后立即更新 URL、清空旧结果并重算。浏览器返回/前进恢复已提交组合和 tab，临时选择不污染历史。
- 请求 key 包含 A/B、tab 和分页/筛选条件；AbortController 取消旧请求，并用 key 校验响应，禁止旧组合覆盖新结果。切换组合清空展开行与分页。终态比较不自动轮询。
- 初次加载显示骨架/加载状态，不显示假 0。失败提供原位重试；新闻或证据分页失败不遮盖已加载的候选表。
- 查询错误 404/409/422 说明原因并保留用户选择；来源/分类提示不得统一隐藏成“没有数据”。运行数不足两次时链接返回历史或新建分析，不自动创建运行。
- dialog 使用 showModal、Esc 关闭、焦点限制和关闭后回到触发控件；tab 遵循键盘方向键及 aria-selected、关联 tabpanel。标题、状态、表格均可被辅助技术读取。

## 6. 只读接口契约

新前缀 `/api/run-comparisons`，避免和 `/api/data-runs/{run_id}` 冲突。端点使用同步 `def` 包装同步仓储，由框架在线程池执行；不在 async 端点直接阻塞事件循环。

| GET 路径 | 参数 | 返回 |
| --- | --- | --- |
| `/api/run-comparisons/runs` | provider?、mode?、offset=0、limit=20（1–100） | RunOptionPage |
| `/api/run-comparisons` | base_run_id、compare_run_id | RunComparisonView |
| `/api/run-comparisons/news` | 两个运行 ID、membership=ALL/BOTH/ONLY_BASE/ONLY_COMPARE、offset=0、limit=20 | NewsComparisonPage |
| `/api/run-comparisons/evidence` | 两个运行 ID、kind?、sector_id?、offset=0、limit=20 | EvidenceComparisonPage |

sector_id 与 kind 同时提供或同时省略；首版证据接口不提供仅 kind 的服务器筛选。前端候选 kind 筛选在已加载结果内进行。所有分页 offset >=0、limit 1–100；每个端点都重新验证运行对，不依赖前端先调用主接口。

统一结构约定：UTC ISO 时间字符串；UUID 为字符串；Decimal 为字符串；不存在的字段显式 null；数组均返回数组。Pydantic response_model 和对应 TS 类型作为实现契约，不用散落的 `dict[str, Any]` 代替整个接口。

### 类型字典（字段全部列出）

| 类型 | 字段 |
| --- | --- |
| RunOption | run_id: UUID；provider: fixture/live；mode: intraday/post_close；status: RealDataRunStatus；requested_at/cutoff_at/finished_at: datetime（后两项可 null）；lookback_hours、precandidate_limit、final_candidate_limit: int；error_code: string/null |
| RunOptionPage | items: RunOption[]；total、offset、limit: int |
| ComparisonWarning | code: string；message: string；side: BASE/COMPARE/BOTH；kind: SectorKind/null |
| SnapshotContext | provider_id、classification_version、source_version: string；observed_at、collected_at: datetime；available_fields: string[] |
| KindComparison | kind: SectorKind；status: COMPARABLE/UNAVAILABLE/INCOMPATIBLE；base/compare: SnapshotContext/null；rows: SectorComparisonRow[] |
| MetricDifference | base、compare、delta: Decimal/null；unit: percentage_points/count；base_reason、compare_reason: VALUE_MISSING/FIELD_UNDECLARED/SECTOR_MISSING/null |
| SectorComparisonRow | sector_id: string；kind: SectorKind；base_name、compare_name: string/null；membership: BOTH/ONLY_BASE/ONLY_COMPARE；base_rank、compare_rank、rank_delta: int/null；base_score、compare_score: Decimal/null；base_leader、compare_leader: string/null；pct_change、turnover_rate、advancers、decliners: MetricDifference |
| CandidateCounts | both、only_base、only_compare、unavailable_kinds: int |
| NewsCoverage | lineage: RECORDED/UNVERIFIABLE；recorded_count: int |
| NewsCounts | both、only_base、only_compare: int |
| RunComparisonView | base/compare: RunOption；queried_at: datetime；warnings: ComparisonWarning[]；candidates: CandidateCounts；kinds: KindComparison[]；base_news/compare_news: NewsCoverage；news_counts: NewsCounts/null |
| CurrentNewsMetadata | title、source_id: string；publisher、summary、citation_url: string/null；published_at: datetime/null；metadata_scope: 固定 CURRENT_STORED |
| NewsComparisonRow | document_id: string；membership: BOTH/ONLY_BASE/ONLY_COMPARE；metadata: CurrentNewsMetadata/null |
| NewsComparisonPage | available: bool；reason: LINEAGE_UNVERIFIABLE/null；base_news/compare_news: NewsCoverage；counts: NewsCounts/null；items: NewsComparisonRow[]；total: int/null；offset、limit: int |
| EvidenceLinkView | relation_type、mapping_confidence、mapping_reason、rule_version: string |
| EvidenceComparisonRow | sector_id、event_id: string；kind: SectorKind；membership: BOTH/ONLY_BASE/ONLY_COMPARE；base/compare: EvidenceLinkView/null；current_event_title: string/null；metadata_scope: 固定 CURRENT_STORED |
| EvidenceComparisonPage | items: EvidenceComparisonRow[]；total、offset、limit: int；unavailable_kinds: SectorKind[] |

CandidateCounts 只计 COMPARABLE 类别中的候选；无法比较的类别数单独展示，不把它们计作全部未入选。NewsComparisonPage.available=false 时 counts、total 为 null，items=[]，保留双方 coverage。证据按 kind、sector_id、event_id 稳定排序。

### 错误与提醒

- 404：任一数据运行不存在；仅有内容运行不满足条件。
- 422：UUID、分页或筛选参数非法；两侧相同；kind/sector_id 缺一。
- 409：任一数据运行未结束，或 provider/mode 不同。
- 两侧存在但分类不可比或数据缺失，主接口仍 200，分组状态与 warnings 说明；即使全部不可比，也返回真实上下文和返回原运行入口。
- 沿用全站 HTTP 错误包装与脱敏；不把连接字符串、SQL、供应商密钥返回浏览器。
- warning code 固定集合：SOURCE_VERSION_DIFF、NEWS_WINDOW_DIFF、CANDIDATE_LIMIT_DIFF、RUN_PARTIAL、CUTOFF_MISSING、REVERSED_TIME、CLASSIFICATION_MISMATCH、SNAPSHOT_MISSING、FIELD_SCHEMA_UNKNOWN、NEWS_LINEAGE_UNVERIFIABLE、CURRENT_NEWS_METADATA。不把每个缺失单元格重复为顶部告警；行级原因已覆盖。

## 7. 实现边界

新增只读 `RunComparisonQueries`，注入 RuntimeStorageBundle，仅消费 real_data_runs、market_snapshots、news_retrieval、news。对比算术和集合规则放入纯函数模块，便于用固定数据验证；不从 LLM 服务或运行命令服务取值。

运行仓储增加 `list_comparison_runs(provider, mode, offset, limit)` 的类型化分页方法，SQLite/PostgreSQL 同时实现，既有 list_runs 行为不变。按终态过滤，使用同一条件计算 total 和 items，SQL 参数化，排序有 ID 次级键。列表 total 是查询时统计；翻页时出现新运行可改变位置，不承诺历史列表事务快照。

新闻先用 ID 去重和分页，再批量读该页元数据；最多读取 100 个不同文档。事件也仅批量读取当前页 ID，不能逐行查询。集合层允许读取两次运行的全部关联 ID，不加载全库正文。无需新闻回填或 schema 019。

## 8. 阶段与验收

| 阶段 | 可独立验收的交付 | 验收重点 |
| --- | --- | --- |
| 1：可信只读后端 | 差异规则、双数据库分页、四个接口 | 精确小数、缺失值、kind 同码隔离、终态/来源限制、新闻元数据边界、全部 GET 无业务写入 |
| 2：对照工作台 | 选择器、候选表、新闻/证据、原有页面入口 | URL 恢复、请求竞态、键盘与窄屏、统一侧栏、无自动重新采集 |
| 3：完整交付 | 双数据库集成、生产/开发浏览器验收、文档实图与构建 | 单元/契约/HTTP/E2E 门槛、无业务库污染、不把 Fixture 验收冒充 Live 可用 |

验收必须覆盖：两种分类使用相同 ID；A/B 交换；同一运行；超过 50 条历史；同时间分页；未知字段与真实 0；单侧未入选但行情存在；旧新闻无 lineage；重复文档；元数据被更新或删除；同标题不同 ID；source/classification 不一致；运行已失败但有部分快照；新闻分页失败和旧请求晚到。

完成判据：所有约定能力实现并有新鲜验收结果，README 的功能与截图来自实际构建；不将当前设计稿标记为已交付功能。
