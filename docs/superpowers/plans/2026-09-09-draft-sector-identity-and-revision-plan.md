# 草稿主体与真实修订实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 本项目按用户要求在当前会话执行，不使用子代理。

**Goal:** 让每个章节明确对应可信板块，并以实际内容修订替代追加系统标记。

**Architecture:** 名称从同次运行快照进入归因上下文，再由后端校准分析卡。独立的内容校验和修订模块负责生成质量边界，管线负责有限轮次、预算、持久化和逐版本复审。历史修复使用显式目标和预览，不改变已有业务版本。

**Tech Stack:** Python、Pydantic、pytest、SQLite/PostgreSQL、现有 LLMPort 和 PromptRegistry。

**Spec:** `docs/superpowers/specs/2026-09-09-draft-sector-identity-and-revision-design.md`

## Global Constraints

- 不根据章节顺序、新闻关键词或领涨股猜板块名称。
- 不伪造复核结果，不降低证据等级、引用和发布检查标准。
- 不覆盖旧版本，不继承旧版本的批准来发布新内容。
- 保持 SQLite/PostgreSQL 支持；优先利用已有 JSON 载荷、版本和审计结构，不新增数据库列。
- 不重新采集行情或新闻来修正文案；修订使用该运行已保存的事实与证据。
- 默认以 Fixture 和隔离数据库测试；真实 LLM 验证需另行说明次数与费用，不自动使用用户额度。
- 当前会话执行，不使用子代理；合并和推送仍需单独指示。
- 历史 apply 必须单独确认具体目标及 dry-run 差异。
- 保留工作区上轮行情阻断修复，不混入本轮草稿提交。

## Task 1：可信名称贯穿归因链路

Files:
- Modify: `backend/src/sector_pulse/domain/writing/attribution.py`
- Modify: `backend/src/sector_pulse/application/writing/attribution_gate.py`
- Modify: `backend/src/sector_pulse/application/writing/agent_validation.py`
- Modify: `backend/src/sector_pulse/application/writing/attribution_agents.py`
- Test: `backend/tests/unit/application/writing/test_agent_validation.py`
- Test: `backend/tests/unit/application/writing/test_attribution_gate.py`

Interfaces: `AttributionContext.sector_name: str | None = None`、`SectorAnalysisCard.sector_name: str | None = None`；`validate_analysis_card(card, gate, context)` 返回以 context 为准的名称，拒绝类型错配。

- [x] 写失败测试：成功输出中的模型伪造名称被覆盖、降级保留名称、旧 JSON 缺字段仍可读、同 ID 不同类型被拒绝。

```python
assert validate_analysis_card(card, gate, context).sector_name == "文化传媒"
with pytest.raises(AgentOutputViolation):
    validate_analysis_card(wrong_kind_card, gate, context)
```

- [x] 运行 `test_agent_validation.py` 和 `test_attribution_gate.py`，确认缺名称或错误类型未被拦截导致失败。
- [x] 构建 context 时写入 `sector_name=snapshot.name`；成功校准及降级均保留 context 名称。
- [x] 再运行新增测试及全量非 Live 测试，包含写作桥接测试。

## Task 2：可定位的确定性内容检查

Files:
- Create: `backend/src/sector_pulse/application/writing/draft_quality.py`
- Modify: `backend/src/sector_pulse/application/writing/editorial_agents.py`
- Modify: `config/prompts/writing.yaml`
- Test: `backend/tests/unit/application/writing/test_draft_quality.py`

Interfaces: `sector_subject(card: SectorAnalysisCard) -> str`；`draft_quality_issues(draft: ArticleDraft, cards: Mapping[str, SectorAnalysisCard]) -> tuple[ReviewIssue, ...]`。名称缺失使用类型和 ID；问题码定位章节，未知身份不能放行。

- [x] 写失败测试，覆盖泛称标题、首句缺主体、系统后缀、未知/重复板块、正确名称与可追溯降级。

```python
codes = {issue.code for issue in draft_quality_issues(draft, cards)}
assert "SECTOR_SUBJECT_MISSING" in codes
assert "WORKFLOW_MARKER_IN_ARTICLE" in codes
```

- [x] 运行新增测试确认缺失实现；实现逐章节及全局字段校验，不对正文静默猜名或替换。
- [x] 写作请求增加明确主体映射，校验大纲/运行/章节身份；首轮内容问题交给后续修订，不标通过。
- [x] 运行新增测试及 editorial agent 测试。

## Task 3：结构化真实修订与逐版审核

Files:
- Create: `backend/src/sector_pulse/application/writing/revision_agent.py`
- Modify: `config/prompts/revision.yaml`（已有简单提示词，升级为 1.1.0）
- Modify: `backend/src/sector_pulse/application/writing/phase1b_pipeline.py`
- Modify: `backend/src/sector_pulse/application/writing/editorial_agents.py`
- Test: `backend/tests/unit/application/writing/test_revision_agent.py`
- Test: `backend/tests/integration/test_phase1b_pipeline.py`
- Test: `backend/tests/integration/test_phase1b_pipeline_progress.py`

Interfaces: `RevisionChanges` 仅允许显式章节修改和全局文本字段；`run_revision_agent(draft, review, cards, llm, prompt, invocation_sink, model)` 返回候选及安全错误码。未知修改目标、超范围字段、无变化均失败；管线只对成功候选递增版本。

- [x] 写失败测试：实际修改后 v2 内容变化，不包含系统后缀；未涉及全局字段保持不变。

```python
assert result.draft.version == 2
assert result.draft.sections[0].body == revised_body
assert result.draft.sections[1] == original.sections[1]
assert "（已复核）" not in result.draft.sections[0].body
```

- [ ] 增加无变化、未知 claim/section、非法来源/证据等级、越界修改、版本错配审核、修订失败及两轮上限测试，运行确认失败。
- [x] 实现额外字段禁止的修改模型、整批候选验证、真实 revision 路由调用及调用记录；禁止整稿身份替换。
- [x] 移除管线追加后缀逻辑；合并确定性问题与模型审核，保留 BLOCK；调用前后预算检查。自定义 invocation sink 不能使内部成本归零。
- [x] 发出 revision.started/done/failed，逐版重审；失败保留最新有效版本，未通过不能进入人工发布就绪。
- [x] 运行修订单元及管线集成测试，更新 Fixture 为真实修改集，不保留依赖假修订的测试。

## Task 4：旧输入恢复与历史修复

Files:
- Modify: `backend/src/sector_pulse/application/data_runs/real_data_writing_bridge.py`
- Create: `backend/src/sector_pulse/application/writing/draft_repair.py`
- Create: `scripts/repair_draft_identity.py`
- Modify: `backend/src/sector_pulse/storage/sqlite/review/draft_edit_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres/review/draft_edit_repository.py`
- Test: `backend/tests/integration/test_draft_identity_repair.py`

Interfaces: 修复输入为明确 run_id/draft_id/expected_version；输出为字段差异和无法解析项。dry-run 不写库；apply 复核版本并原子保存新版本和审计。

- [ ] 追踪旧输入恢复入口；仅按同运行 `(sector_kind, sector_id)` 快照补名称，无唯一映射则报告缺失。
- [ ] 写 dry-run 零写入、保留中间正常引用字样、只清理末尾系统后缀测试；用原始/结果正文的文字常量独立断言。
- [ ] 实现安全差异生成，示例断言 `assert preview.after.version == original.version + 1`，`assert repository.latest_version(draft_id) == original.version`。
- [ ] 写 apply 事务回滚、冲突拒绝、旧批准不继承及重复执行不生成版本测试，确认失败后实现双方言原子事务。
- [ ] 命令行默认 dry-run，apply 要求显式开关与目标；实际业务只交付预览，不自行 apply。

## Task 5：验收与文档

- [ ] 后端运行非 live、非 live_llm、非 postgres 全量测试；进程内显式设置数据库 URL 为空、LLM 为 fixture，禁用调度。
- [ ] 运行 `.venv/Scripts/python.exe -m ruff check backend` 和 `.venv/Scripts/python.exe -m mypy backend/src/sector_pulse`。
- [ ] 有隔离 PostgreSQL URL 才执行该集成组，否则明确未验证，不使用业务库做破坏性测试。
- [ ] 检查事件消费者；若改前端，执行前端测试及构建。
- [ ] 补充版本/修订含义、错误码、历史预览/apply 流程及验收记录；分别标明代码、Fixture、真实 LLM 与历史写入状态。
- [ ] 按本轮明确文件提交，不合并、不推送。

## 执行记录

2026-09-09：设计已获用户确认；开始 Task 1。未调用真实 LLM，未改业务数据库。

2026-09-09 本批：Task 1、2 已实现，Task 3 核心闭环已实现。补充了项目自带 Fixture 的明确主体和实际字数，并修复外部 invocation sink 导致管线成本统计归零的问题。Task 3 的完整边界测试（含更多多章节范围、BLOCK、超时）和 Task 4、5 仍待完成，不将本批测试通过视为整个设计交付。
