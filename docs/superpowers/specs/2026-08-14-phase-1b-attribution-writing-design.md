# SectorPulse Phase 1B 谨慎归因与成文设计

## 1. 背景与目标

Phase 1A.2 已建立 A 股行业/概念板块行情、真实新闻检索、事件去重、实体映射、质量门禁和证据包。本阶段在这些结构化事实之上增加谨慎归因与成文能力，生成一篇供用户人工审核的通用社区稿。

Phase 1B 的目标是：

- 对 8～12 个候选板块形成可追溯的结构化归因分析；
- 精选 3～6 个涨跌突出、散户关注度高、新闻丰富或异动明显的板块；
- 生成一篇约 1000～1800 字的通用社区稿；
- 正文简短标注来源，文末附可核验的来源清单；
- 严格区分“明确驱动、可能催化、市场联想、暂无可靠解释”；
- 无可靠因果证据时拒绝强行归因；
- 保存模型调用、Prompt、Claim、来源、审核和草稿版本记录；
- 只生成待人工审核的草稿，不实现自动发布。

第一轮开发使用可重复的 Fixture LLM Provider。接口稳定后再进行显式启用的真实模型验收。

## 2. 设计原则

1. 确定性程序负责事实边界，模型不得修改行情、时间、来源和证据等级上限。
2. 新闻与板块相关不等于新闻造成板块涨跌。
3. Agent 可以主动降级归因，但不能突破程序计算的上限。
4. 每个正文 Claim 必须绑定可追溯的行情事实或新闻证据。
5. 单个板块失败不得取消其他板块分析。
6. 局部审核失败只返工对应区块，不整篇重写。
7. Provider、Prompt、Agent 和持久化通过 Port 解耦，便于替换模型和增加插件。
8. 不保存 API Key、模型思维过程或新闻完整正文。

## 3. 总体架构

```text
Phase 1A.2 EvidencePack
        │
        ▼
确定性证据门禁
时间 / 来源 / 板块特异性 / 市场印证 / 替代解释
        │
        ▼
板块归因 Agent × 3～12（受控并发）
        │
        ▼
选题编辑 Agent
        │
        ▼
成文 Agent
        │
        ▼
事实与合规审核 Agent
        │
        ├── PASS → 待人工审核草稿
        ├── REVISE → 局部返工，最多两轮
        └── BLOCK → 保存产物但禁止发布
```

Phase 1B 使用轻量应用编排器，不引入 LangGraph。所有节点使用稳定的输入输出契约，Phase 2 可在不改领域模型的情况下装配进状态图。

## 4. 归因等级

### 4.1 EXPLICIT_DRIVER（明确驱动）

必须同时满足：

- 政策、监管、公司公告或高可信媒体明确表达事件与对应产业的影响；
- 发布时间早于或位于板块异动前段；
- 板块广度、成交活跃度或多只成分股出现同步响应；
- 没有更强的市场级替代解释。

只凭新闻与上涨同时出现不得判为明确驱动。

### 4.2 POSSIBLE_CATALYST（可能催化）

事件与板块存在清晰产业逻辑和合理时序，行情也有一定印证，但缺少直接因果表述、板块响应不够广，或仍存在其他合理解释。

### 4.3 MARKET_ASSOCIATION（市场联想）

新闻与板块存在实体或主题关联，但时序、来源、板块特异性或市场印证不足。正文只能使用“消息受到关注”“市场可能产生联想”等审慎表述。

### 4.4 NO_RELIABLE_EXPLANATION（暂无可靠解释）

没有合格新闻、新闻晚于异动、只有背景材料、映射存在歧义，或替代解释强于新闻解释时使用。相关新闻可作为背景简要提及，但不能解释走势。

## 5. 确定性归因门禁

每个候选板块生成 `AttributionContext` 和 `AttributionGateResult`。门禁先计算 `allowed_max_level`，模型只能选择不高于该上限的等级。

硬规则如下：

- `published_at` 缺失：最高为 `MARKET_ASSOCIATION`；
- `published_at` 或 `source_observed_at` 晚于本轮 cutoff：证据直接排除；
- 只有发现型来源且没有可核验链接：最高为 `MARKET_ASSOCIATION`；
- 只命中歧义词且没有板块特异性：不得进入归因；
- 新闻发生在板块明显异动之后：不得成为此前走势的驱动证据；
- 仅单只个股上涨、板块广度没有响应：通常最高为 `POSSIBLE_CATALYST`；
- 同期大盘或同类板块普涨：写入反证并降低板块特异性；
- Agent 输出超过 `allowed_max_level`：解析器拒绝并记录 `ATTRIBUTION_LEVEL_EXCEEDED`。

等级顺序固定为：

```text
NO_RELIABLE_EXPLANATION < MARKET_ASSOCIATION < POSSIBLE_CATALYST < EXPLICIT_DRIVER
```

## 6. Agent 职责与契约

### 6.1 板块归因 Agent

每个候选板块独立运行，可受控并发。输入为只读 `AttributionContext`：

- 板块行情事实与异动时段；
- 合格新闻事件及短摘要；
- 时间关系与板块实体映射；
- 成交、涨跌家数、龙头和拖累股；
- 市场背景与替代解释；
- `allowed_max_level`。

输出 `SectorAnalysisCard`：

- 最终归因等级和置信度；
- 一句话结论；
- 支持证据 ID；
- 反证与不确定性；
- 与走势无关但可简要提及的背景新闻；
- 可写入正文的 Claim；
- 禁止写入正文的推测；
- 不含买卖建议的关注角度。

板块归因 Agent 不负责选择最终发稿板块，也不写整篇文章。

### 6.2 选题编辑 Agent

输入全部通过程序校验的 `SectorAnalysisCard`，精选 3～6 个板块。选择依据包括：

- 涨跌幅、成交活跃度和板块广度；
- 涨停或异动个股；
- 新闻数量、时效和证据质量；
- 面向非专业投资者的关注度与可读性；
- 行业板块与概念板块的内容多样性；
- 避免多个板块重复讲同一事件。

输出 `ArticleOutline`：板块顺序、入选理由、标题方向、文章主线、段落字数预算和未入选原因。

### 6.3 成文 Agent

只能读取 `ArticleOutline`、入选分析卡和允许引用的来源元数据，输出 `ArticleDraft`：

- 2～3 个备选标题；
- 简短导语；
- 3～6 个板块段落；
- 市场总结；
- 风险提示；
- 正文简短来源标记；
- 文末来源清单。

正文目标 1000～1800 字，专业但适合社区阅读，可以增强情绪和阅读节奏，但不得喊单、预测涨停、暗示确定性收益或给出仓位建议。

### 6.4 事实与合规审核 Agent

输入草稿及全部结构化 Claim，输出 `ReviewReport`：

- 数字是否与行情事实一致；
- 来源标记是否存在且可引用；
- 归因措辞是否超过证据等级；
- 是否遗漏重要反证；
- 是否包含荐股、收益暗示或绝对化判断；
- 问题区块、原因和允许的修订范围；
- `PASS`、`REVISE` 或 `BLOCK`。

`REVISE` 只返工问题区块，最多两轮。两轮后仍未通过时保留草稿和审核报告，但草稿状态必须为不可发布。

## 7. LLM Provider 与模型路由

应用层只依赖统一 `LLMPort`：

```python
class LLMPort(Protocol):
    async def generate_structured(self, request: LLMRequest[T]) -> LLMResult[T]: ...
    async def health_check(self) -> LLMHealth: ...
    def estimate_cost(self, usage: TokenUsage) -> Money: ...
```

首批实现：

- `FixtureLLMProvider`：自动测试和开发使用，输出固定且可重复；
- `OpenAICompatibleProvider`：支持可配置 `base_url`、模型和本地密钥；
- 后续插件 Provider：实现相同 Port 即可接入。

模型路由：

- 板块归因使用低成本结构化模型并发执行；
- 选题和成文使用质量较高的模型，各调用一次；
- 审核优先使用与成文不同的模型或独立 Prompt；
- 局部返工只发送问题区块及必要证据。

第一版支持单 Provider、多模型配置，不实现跨厂商自动竞价。

API Key 只从环境变量或本机密钥文件读取，不进入日志、数据库和报告。

## 8. Prompt 管理

Prompt 使用版本化 YAML：

```text
config/prompts/
├── attribution.yaml
├── editorial.yaml
├── writing.yaml
├── review.yaml
└── revision.yaml
```

每个 Prompt 包含：

- `prompt_id`、版本和内容哈希；
- 系统职责；
- 输入字段说明；
- 证据等级边界；
- 禁止行为；
- 输出 JSON Schema；
- 少量正例与反例；
- 最大 Token、温度和建议模型档位。

数据库记录实际使用的 Prompt 版本和内容哈希，保证历史结果可追溯。

## 9. 结构化输出校验

模型输出依次经过：

1. JSON 解析；
2. Pydantic Schema 校验；
3. ID 白名单校验；
4. 数字一致性校验；
5. 归因等级上限校验；
6. 禁止表达扫描；
7. 来源引用完整性校验。

Prompt 不能替代程序校验。非法输出不进入后续节点和持久化主结果，但保存脱敏后的失败审计元数据。

## 10. 错误和降级

- 单个板块归因失败：重试一次，仍失败则生成“暂无可靠解释”的降级分析卡；
- 部分板块失败：其他板块继续；
- 选题 Agent 失败：使用确定性综合得分选择 3～6 个板块；
- 成文 Agent 失败：保留分析卡和提纲，标记 `DRAFT_GENERATION_FAILED`；
- 审核 Agent 失败：保留草稿但标记 `UNREVIEWED`，不可发布；
- Provider 不可用：保存错误码、阶段和重试记录，允许未来从检查点继续；
- 内容截断：缩小上下文后重试一次，不拼接残缺文章；
- 超过单次成本预算：停止后续调用，保存已有产物并标记 `BUDGET_EXCEEDED`。

默认单次模型预算上限为人民币 2 元，可配置。每天约两次运行时，目标月成本为 50～100 元。

## 11. 领域模型

新增不可变对象：

- `AttributionContext`
- `AttributionGateResult`
- `SectorAnalysisCard`
- `Claim`
- `ArticleOutline`
- `ArticleDraft`
- `ArticleSection`
- `ArticleSource`
- `ReviewIssue`
- `ReviewReport`
- `AgentInvocation`

文章按区块保存。局部返工生成新的草稿版本，不覆盖旧版本。

## 12. SQLite 持久化

新增迁移表：

- `attribution_contexts`
- `attribution_gate_results`
- `sector_analysis_cards`
- `claims`
- `article_outlines`
- `article_drafts`
- `article_sections`
- `article_sources`
- `review_reports`
- `review_issues`
- `agent_invocations`

所有记录通过 `run_id` 关联 Phase 1A.2 数据。草稿使用独立 `draft_id` 和递增 `version`。模型调用审计保存模型、Provider、Prompt 版本、输入输出哈希、耗时、Token、估算成本和状态。

不保存 API Key、模型思维过程和新闻完整正文。

## 13. 执行流程

```text
读取 Phase 1A.2 EvidencePack
→ 构建 AttributionContext
→ 执行确定性归因门禁
→ 并行运行板块归因 Agent
→ 校验并保存 SectorAnalysisCard
→ 结合确定性综合得分排序
→ 选题编辑 Agent 精选 3～6 个板块
→ 校验 ArticleOutline
→ 成文 Agent 生成分区草稿
→ Claim、数字和引用程序校验
→ 事实与合规审核 Agent
→ 必要时局部返工，最多两轮
→ 输出 JSON、Markdown 和纯文本草稿
```

只有同时满足以下条件，草稿才能标记为 `READY_FOR_HUMAN_REVIEW`：

- 至少 3 个有效板块分析卡；
- 所有正文数字都能匹配结构化行情事实；
- 所有新闻引用都能匹配合格来源；
- 归因措辞没有超过对应等级；
- 没有阻断级合规问题；
- 审核 Agent 返回 `PASS`；
- 总成本没有超过配置上限。

否则必须保存为 `INCOMPLETE`、`REVISE_REQUIRED`、`UNREVIEWED` 或 `BLOCKED`，不能作为可发布成稿展示。

## 14. 测试策略

### 14.1 领域单元测试

覆盖归因等级顺序、证据上限、Claim 引用、草稿版本和状态机。

### 14.2 门禁规则测试

覆盖未来新闻、发布时间缺失、发现型来源、个股独涨、大盘普涨、新闻晚于异动、歧义映射和替代解释。

### 14.3 Agent 契约测试

使用 Fixture Provider 验证结构化输出、非法 ID、数字篡改、越级归因和截断响应。

### 14.4 编排集成测试

验证并发顺序、单板块失败隔离、确定性降级、局部返工、预算中止及产物状态。

### 14.5 可选真实模型测试

必须显式启用并提供 API Key。测试只校验 Schema、引用、边界和成本，不断言固定文案。

## 15. 验收标准

Fixture 端到端必须满足：

- 输入 8～12 个候选，输出 3～6 个重点板块；
- 生成一篇 1000～1800 字通用稿；
- 每个数字和新闻引用均可追溯；
- 越级归因被程序拒绝；
- 无可靠证据时可以输出“暂无可靠解释”；
- 单个归因 Agent 失败不影响整轮；
- 审核问题只返工对应区块；
- 两轮返工后仍不通过则阻断发布；
- 输出 JSON、Markdown 和纯文本；
- Fixture 结果可重复；
- 单次预算门禁和调用审计完整。

真实模型验收使用 10～20 个固定历史或人工构造样本，统计结构化输出成功率、引用正确率、数字一致率、归因越级率、“暂无可靠解释”保留率、审核一次通过率、平均耗时、Token、成本和人工大改比例。

## 16. 本阶段范围外

Phase 1B 不实现：

- Web 管理台；
- 定时调度和失败恢复界面；
- 自动发布；
- 社区热度爬取；
- 长期写作偏好学习；
- 多用户、权限和计费；
- LangGraph 持久化状态图；
- 投资建议、目标价、确定性预测或仓位建议。

这些能力分别留给 Phase 1C 和 Phase 2。Phase 1B 的交付边界是可追溯的谨慎归因、结构化多 Agent 链路和一篇可供人工审核的通用稿。

## 17. 完成定义

Phase 1B 只有在以下条件全部满足时才视为实现完成：

1. Fixture 多 Agent 链路通过全部自动测试；
2. 门禁、Schema、引用、数字和合规校验均为程序化实现；
3. 生成的草稿满足板块数量、篇幅、来源和状态要求；
4. 所有 Agent 调用和草稿版本可审计；
5. 真实模型调用仍保持显式开关，缺少密钥时不触网；
6. 真实模型验收结果与 Fixture 自动测试结果分开报告。
