# A 股板块分析文案助手 Master Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以可独立验收的阶段交付完整的 A 股行业/概念板块分析文案助手，同时把免费数据源、新闻归因、人工审核和合规风险逐步关进可测试边界。

**Architecture:** 采用模块化单体、Ports & Adapters、显式可恢复工作流和四类有界 Agent。总规格覆盖多个相对独立的子系统，因此不使用一份巨型实施计划；每个阶段在上一个阶段真实验收后再形成下一份逐文件计划。

**Tech Stack:** Python 3.12+、FastAPI、Pydantic v2、SQLAlchemy 2、SQLite/PostgreSQL、React、TypeScript、Vite、OpenAPI、pytest、Playwright、Docker Compose。

## Global Constraints

- 市场范围固定为 A 股行业板块 + 概念板块。
- 每轮只生成一篇通用社区稿，不做平台专属稿，不接入自动发布。
- 正文约 1000～1800 字，通常选择 3～6 个重点板块；证据不足时允许少写并说明原因。
- 所有行情事实由程序计算；LLM 不得创造数字、来源 URL 或移动 cutoff。
- 归因等级固定为“明确驱动、可能催化、市场联想、暂无可靠解释”。
- 代表性个股只能解释板块结构，禁止买卖、持仓、仓位、目标价和确定性预测。
- 调度支持盘中、盘后自定义时间和手动执行；同日多次运行必须独立版本化。
- LIVE 任务在核心行情采集和质量检查后锁定实际 `run_cutoff_at`；AS_OF 任务启动时锁定指定 cutoff。
- 正常模型月成本目标不超过 50 元，100 元为硬上限；数据授权费用单列。
- 用户审核中位数目标不超过 5 分钟，正常任务 P90 不超过 15 分钟。
- 写作偏好只有在用户明确采纳后生效，且不得覆盖事实、证据、时间和合规规则。
- 第一版单用户、自托管；API 密钥只保存在本机凭据库或容器 Secret。
- 免费/低成本 Provider 只能用于开发和影子期；公开稳定使用前逐项确认授权、缓存和二次展示边界。
- 所有实现任务必须先写失败测试，再写最小实现，再运行验证并小步提交。
- 不提前引入 Redis、MongoDB、消息队列、向量数据库、微服务集群或自由 Agent 群聊。

---

## 1. 计划拆分与依赖

| 顺序 | 子计划 | 独立可验收产物 | 开始条件 |
|---:|---|---|---|
| 0 | `2026-08-13-phase-0-foundation-and-market-data-spike.md` | 可追溯的真实行业/概念快照、cutoff 契约、Provider 契约、Phase 0 候选雷达 | 总体规格已批准 |
| 1A | Phase 1A：市场/新闻垂直切片 | SQLite 中的行情、新闻事件、候选与证据包 | Phase 0 明确真实字段、覆盖率和来源风险 |
| 1B | Phase 1B：归因/成文垂直切片 | 3～6 板块结构化分析、一篇通用稿、确定性来源清单 | Phase 1A 领域对象稳定 |
| 1C | Phase 1C：基础 Web 工作台 | 手动运行、SSE 进度、雷达、草稿和证据查看 | Phase 1B API 契约稳定 |
| 2A | Phase 2A：可靠任务与调度 | 自定义盘中/盘后调度、检查点、幂等、重试、降级 | Phase 1 连续 5 个交易日通过 |
| 2B | Phase 2B：五分钟审核与治理 | 全文编辑、证据决策、局部重写、版本、成本、偏好 | Phase 2A 任务状态稳定 |
| 3 | Phase 3：20 个交易日影子验收 | Prompt 黄金集、质量指标、恢复演练、合规复核记录 | Phase 2 验收通过 |
| 4 | Phase 4：个人服务器与插件演进 | Docker Compose、PostgreSQL/S3、按需插件 | 真实瓶颈或正式 Provider 合同出现 |

Phase 1A 之后的详细计划不在本轮提前固化。原因是 AKShare/Tushare 等真实字段、板块分类覆盖、发布时间质量和访问限制会直接改变数据库迁移、Provider 映射和质量阈值。每份后续计划必须引用上一阶段的真实验收报告，而不是沿用推测。

## 2. 总体交付门

### Gate 0：数据与契约可行

- 一个真实交易日的行业和概念板块都能生成规范化快照。
- 所有快照有 Provider、分类版本、`observed_at`、`collected_at` 和锁定 cutoff。
- 行业/概念覆盖达到 Phase 0 计划中的最低阈值。
- 数据源失败、空数据、陈旧数据和不支持历史查询能够明确区分。
- Provider 授权状态为未核实时，系统明确阻止将其标记为正式公开生产源。

### Gate 1：最窄业务闭环可用

- 连续 5 个交易日生成候选、证据和一篇通用稿。
- 任何数字、公司名和来源主张都能回溯。
- cutoff 后信息为零。
- 没有可靠新闻时能输出“暂无可靠解释”。

### Gate 2：日常使用可维护

- P90 生成不超过 15 分钟。
- 人工审核中位数不超过 5 分钟。
- Provider 故障不会被错误解释为“没有新闻”。
- 月度模型成本投影不超过 50 元，100 元硬停止有效。
- 核准前事实、引用和合规门禁全部通过。

### Gate 3：可以进入持续公开创作评估

- 20 个交易日影子运行达到总体规格第 20 节指标。
- 备份在空目录真实恢复成功。
- Prompt 变更通过黄金集回归。
- 已根据具体账号、内容和收益模式完成专业合规复核。

## 3. 跨计划接口冻结顺序

1. Phase 0 冻结时间、Provider 结果、板块快照和质量报告契约。
2. Phase 1A 冻结新闻事件、事实账本、候选选择和证据包契约。
3. Phase 1B 冻结 Agent 输入输出、Claim/Evidence、草稿区块和来源渲染契约。
4. Phase 1C 冻结 REST/SSE 和 Web 审核读取契约。
5. Phase 2 冻结任务恢复、草稿修改、偏好和成本治理契约。
6. Phase 3 只允许兼容性修正，不在影子期随意改变核心评分含义。

后续模块只能依赖已冻结的公共契约，不能直接访问上游模块的数据库表或供应商 DataFrame。

## 4. 预计提交策略

- 每个详细计划 Task 至少一个独立提交。
- 提交只包含该 Task 的代码、测试和必要文档。
- 每个 Gate 使用一个文档提交记录真实命令、结果、Provider 版本和已知限制。
- 不提交 `.env`、密钥、原始网页正文、模型完整响应或 `data/` 运行产物。
- 设计变更先更新规格或 ADR，再修改实现。

## 5. 下一步

先执行详细计划：`docs/superpowers/plans/2026-08-13-phase-0-foundation-and-market-data-spike.md`。

Phase 0 完成并由用户验收后，使用 `superpowers:writing-plans` 根据真实产物编写 Phase 1A 详细计划；不得直接跳到 Agent 或 Web 大规模实现。
