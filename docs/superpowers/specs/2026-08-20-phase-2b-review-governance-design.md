# Phase 2B：五分钟审核与治理设计

## 1. 目标

Phase 2B 在 Phase 1D 的可审核草稿和 Phase 2A 的可恢复任务之上，提供一个可在约五分钟内完成核验的审核台。用户可以编辑结构化草稿、逐段查看事实与证据、保留/降级/驳回证据、局部重写、比较版本并回滚；系统在核准前执行数字、来源、归因和合规门禁。

本阶段继续遵守“草稿/复制/导出、人工发布”的产品边界，不接入任何第三方账号或自动发布接口。

## 2. 核心决策

### 2.1 结构化 Patch + 不可变新版本

`ArticleDraft` 当前版本作为基线，不直接更新 `article_drafts`。每次编辑提交：

```text
base_version + ordered DraftPatch[] -> new_version
```

Patch 只描述字段路径、旧值 hash、新值和操作者；服务端重新组装完整 `ArticleDraft`，执行 Pydantic、事实、来源、归因和合规校验后，以新版本写入。旧版本、Patch、校验结果和审核报告永久保留。

允许的路径：`titles`、`introduction`、`sections/{section_id}/heading`、`sections/{section_id}/body`、`conclusion`、`risk_notice`。禁止直接修改 `source_ids`、`claim_ids`、行情数值、`observed_at`、`run_cutoff_at`、来源 URL 和原始证据正文。

### 2.2 证据裁决

每条证据决策使用 `KEEP`、`DOWNGRADE` 或 `REJECT`。决策关联 `run_id`、draft version、sector/claim/source、原因和操作者。`REJECT` 后，受影响段落必须局部重写；若没有替代证据，生成 `NO_RELIABLE_EXPLANATION` 或删除相应断言，不允许模型自行补造来源。

### 2.3 局部重写

局部重写只把目标段落、关联 Claim、已采纳事实、来源元数据、风控规则和用户指令发送给 LLM。响应必须符合 `ArticleSection` 候选 schema；服务端保留原段落的证据绑定，禁止模型新增未经验证的 `source_id`。LLM 失败不改变当前版本，只记录一次 invocation 和失败原因。

### 2.4 偏好治理

用户修改可以生成 `PreferenceCandidate`，但不会自动影响后续文章。只有显式采纳才产生新的偏好版本；偏好可查看来源、停用和回滚，且永远不能覆盖事实、证据、截止时间和合规规则。

## 3. 领域与持久化模型

新增 SQLite migration：

- `draft_patches`：Patch ID、run/draft/base/new version、ordered operations、input/output hash、操作者和时间。
- `evidence_decisions`：证据对象、决策、原因、影响段落、操作者和时间。
- `rewrite_requests`：目标 section、基线版本、决策集合、状态、LLM invocation、结果版本和错误码。
- `preference_candidates` / `preference_versions`：候选内容、来源 Patch、采纳状态、版本和回滚信息。
- `governance_checks`：版本、检查类型、PASS/FAIL、错误路径、规则版本和时间。

`article_drafts` 继续保持版本不可变；同一 `draft_id + version` 只能对应一个内容 hash。Patch 应用使用数据库条件更新或显式版本比较，`base_version` 不是最新版本时返回 409，而不是静默覆盖。

## 4. 应用服务边界

### `DraftEditingService`

负责读取审核上下文、校验 Patch、创建新版本、生成 Diff、回滚到已有版本和保存审计记录。它不直接调用 Provider。

### `EvidenceDecisionService`

负责保存证据裁决、计算受影响段落，并把需要重写的 section 交给 `RewriteService`。证据决策只能引用系统已持久化的 source/event/claim ID。

### `RewriteService`

负责构造局部重写上下文、调用现有 OpenAI 兼容 Provider、解析候选 section、继承可信来源绑定并创建新版本。所有 LLM 调用沿用现有预算、超时、结构化输出和 invocation 审计。

### `GovernanceService`

执行四类门禁：数字/时间一致性、来源完整性、归因等级约束、合规禁语。检查结果写入 `governance_checks`；只有全部 PASS 才能把版本标记为 `READY_FOR_HUMAN_REVIEW` 或 `APPROVED_FOR_COPY`。

## 5. API

```text
GET  /api/runs/{run_id}/drafts/{draft_id}/versions
GET  /api/runs/{run_id}/drafts/{draft_id}/diff?from=1&to=2
POST /api/runs/{run_id}/drafts/{draft_id}/patches
POST /api/runs/{run_id}/drafts/{draft_id}/rollback

GET  /api/runs/{run_id}/evidence/decisions
POST /api/runs/{run_id}/evidence/decisions

POST /api/runs/{run_id}/rewrites
GET  /api/runs/{run_id}/rewrites/{rewrite_id}

GET  /api/runs/{run_id}/governance
POST /api/runs/{run_id}/approve
GET  /api/preferences/candidates
POST /api/preferences/candidates/{candidate_id}/adopt
POST /api/preferences/versions/{version}/rollback
```

所有写接口带 `base_version` 和幂等键；冲突返回 409，校验失败返回 422，LLM/Provider 失败返回安全错误码。API 不返回 API Key、完整 Prompt 或原始模型响应。

## 6. 前端审核台

在现有 Draft Tab 上增加：

- 左侧文章区块编辑，显示当前版本和未保存 Patch。
- 右侧证据卡：事实值、来源、发布时间、归因等级和 `KEEP/DOWNGRADE/REJECT` 操作。
- 局部重写按钮只作用于选中段落，并显示进行中的 invocation 状态。
- 版本 Diff、回滚、治理检查结果和“核准并复制”按钮。
- 偏好候选单独展示，明确“采纳后影响未来文章”，不把普通编辑自动当作偏好。

## 7. 测试与验收

单元测试覆盖 Patch 路径白名单、旧值 hash、版本冲突、不可变存储、证据决策状态、来源继承和四类治理门禁。

集成测试覆盖：编辑产生新版本、并发编辑冲突、回滚不删除历史、驳回证据触发局部重写、重写失败保留原版本、核准前门禁阻断和偏好只在显式采纳后生效。

端到端验收：打开一篇真实草稿，在五分钟内完成一段编辑、一个证据驳回、一次局部重写、版本 Diff、治理复检和复制终稿；所有操作可从审计事件重放，且没有自动发布调用。

## 8. 非目标与退出条件

- 不做富文本协同编辑、多人权限和实时多人光标。
- 不做账号绑定、平台发布和发布结果追踪。
- 不允许用户编辑事实账本、来源 URL 或 cutoff。

Phase 2B 退出条件：Patch/版本/证据/重写/治理契约冻结；真实草稿五分钟审核路径端到端通过；审核中位数和版本成本可观测；Phase 2A 任务状态持续稳定。
