# 父子 Agent 平台分阶段实施计划

> **For agentic workers:** 使用 executing-plans 在当前会话逐项执行；每阶段按测试先行实现并记录验收。未经用户要求不提交、合并或推送。

**Goal:** 唯一父子 Agent 运行入口，真实使用本地 aidynamic-agent，保留现有真实数据和人工审核能力。

**Architecture:** 框架源码完整内置；框架补丁与业务适配分开。Agent 负责决策，工具负责确定性操作，Skill 负责方法指导。

**Tech Stack:** Python 3.12、aidynamic-agent 0.3.0、Pydantic、SQLite/PostgreSQL、现有 React 前端。

**Spec:** docs/superpowers/specs/2026-09-12-multi-agent-platform-design.md

## 阅读顺序与追踪方式

1. [功能迁移总说明](../specs/2026-09-13-feature-migration-map.md)：先看旧功能如何变成 Agent、Tool、Skill 或保留为基础服务；这是迁移范围的主入口。
2. 本总计划：看实施先后与阶段放行条件。
3. [Phase 2 详细计划](2026-09-13-multi-agent-phase2.md)：看当前阶段具体实现与验证记录。

下文 M 为旧功能迁移项，T 为工具契约，S 为方法 Skill，A 为 Agent 角色，编号均取自主入口。新增设计项未打勾不表示已实现；每个阶段必须记录对应编号、测试证据、剩余缺口。

## Global Constraints

- 完整复用指定框架，不另造 Agent 循环；不复制 .git 或本地环境。
- 最终移除模式开关；迁移完成之前保留可用旧入口，不宣称已切换。
- 现有 YAML 改动、真实运行数据和人工批准规则不丢失。
- 当前会话执行；不注册通用 shell/任意文件读写工具。
- 本总计划下各阶段以独立详细计划实施；不能将未执行项标为完成。

## Phase 1：框架引入与运行安全基础

- [x] 完整复制受控源码，记录来源与 SHA256，验证原始一致性。
- [x] 跑原框架测试，区分已有缺陷与本地修改影响。
- [x] 测试先行修复执行授权、子任务范围、计费、超时和结果状态。
- [x] 保存补丁清单及可复现测试指令；不切换业务入口。

Phase 1 验收：框架排除 Windows 不兼容的 BashTool 测试后 627 passed；当时 SectorPulse 519 passed、5 skipped、24 deselected；项目 Ruff/Mypy 与补丁文件 Ruff 通过。框架 112 个原始文件全部保留，仅 6 个上游文件包含本地修改。

详细计划：2026-09-12-multi-agent-phase1.md。

## Phase 2：调度契约与持久化

- [x] 创建 domain/orchestration 的 Task/Artifact/Budget 契约及 ports/orchestration Repository 接口。
- [x] SQLite/PostgreSQL 增量建表，事件顺序、幂等键、attempt 恢复测试。
- [x] infrastructure/agents 中实现 provider 审计适配、共享预算、角色工厂、受限委派和取消传播。
- [x] 模拟模型验证父子运行与权限/预算隔离，形成阶段详细计划后执行。
- [x] 补全 M24：继承旧人民币额度、未知价格语义，增加工具调用预算；模型调用关联 run/task/attempt/role，不能用预算事件替代完整审计。
- [x] 补全 M21/M30：恢复所有权、迟到 attempt 写入隔离、业务产物与任务索引事务一致性。
- [x] 补全 M29：明确阶段模型路由到角色模型路由的映射，live 配置缺失不静默使用 fixture。

覆盖 M21/M24/M29/M30，提供 A0–A4 的受限角色构造以及 T15–T19 的调度基础。放行要求：实际框架父子测试、权限与预算竞争、取消/恢复/迟到结果测试、SQLite 和专用 PostgreSQL 均通过。不得因快照可重读就宣称调度可恢复。

2026-09-13 进度：已实现共享预算、快照 CAS、双数据库存储适配和框架预算 Provider。SQLite 并发/重开/结算、任务状态迁移、租约恢复与迟到 attempt 隔离测试通过；A0–A4 角色工厂、精确白名单、受限委派和真实框架父子模拟轨迹已具备。PostgreSQL 真实验收、T15–T19 生产工具、子任务并发门禁、旧用量统计关联与业务产物事务仍未完成。详细计划见 2026-09-13-multi-agent-phase2.md；Phase 3–4 未开始。

本轮追加 M24 金额账本与 Provider 价格适配；全量离线 541 passed、5 skipped、25 deselected。生产金额配置接线、工具预算、完整审计仍待完成，不能将金额单元通过视为 Phase 2 完成。

随后完成 M21/M24 的工具调用预算、稳定幂等身份、attempt 隔离和真实框架 Tool 适配；全量离线更新为 552 passed、5 skipped、25 deselected。业务工具注册、角色工厂、恢复所有权、生产配置接线与专用 PostgreSQL 验收仍未完成。

继续完成 M21 状态机/恢复所有权、原子子任务创建与最多两个活动 A2 门禁，以及 A0–A4 角色工厂、受限委派、角色配置/价格映射和 Provider 完整调用身份；随后完成 M30 业务产物同事务、T15/T17–T19 控制工具、旧/新用量统一投影和 T16 生产派发组合。确定性真实框架轨迹执行 A0→delegate→新 A2→业务 Tool→A2 完成→A0。最终使用本机 PostgreSQL 18 隔离实例完成 20 项 PostgreSQL 测试，完整非 Live 回归为 613 passed、7 deselected。Phase 2 已放行；P3/P4 尚未开始。

## Phase 3：按业务能力迁移，而不是只创建 Agent 类

三个子阶段各自先写文件级设计与实施计划，再执行。角色 YAML 放 config/prompts/application/orchestration，方法文档放 config/agent-skills；业务规则继续放代码。工具不得隐藏整段旧模型流水线。

### P3a：数据与选题（M01–M09；A1；T01–T05；S01/S02）

- [x] 从旧数据整链中分离行情、质量、新闻、评分与上下文组装服务，保留来源与快照引用。
- [x] 注册五个工具，让 A1 决定补采和候选提案；评分仍执行原算法。
- [x] 提炼数据缺口、选题方法 Skill，验证只读资源和路径安全。
- [x] 对比旧版同输入评分；验证缺失字段、3–12 个选择、版本冲突、已授权默认选择与人工选择不可混淆。

放行：真实框架调用工具生成可在原数据页面读取的产物；缺口可解释且不会伪造数据；候选提案不冒充用户确认。

当前进度：P3a 已于 2026-09-14 放行。T01–T05、S01/S02、A1 精确权限和真实 A0→A1 框架轨迹均已通过 SQLite 与专用 PostgreSQL 合同；最终非 live 回归 641 passed、1 skipped、6 deselected。该结论不代表 P3、P4 或整个多 Agent 系统完成，下一步进入 P3b。

### P3b：研究与证据（M10–M13；A2；T06–T09；S03/S04）

- [x] 复用旧检索、正文、行情对照和证据校验，用内置框架替换旧归因循环。
- [x] 每个板块隔离作用域，归因卡提交工具强制验证引用、时间和证据资格。
- [x] 提炼因果证据、新闻核验 Skill；新闻文本不能覆盖指令或扩大工具权限。
- [x] 验证补查、反证、无可靠解释、有界失败；跨板块/运行引用与伪造证据必须拒绝。

放行：轨迹能证明 Agent 根据工具观察追加查证；不是将旧单次归因调用换名。旧循环相关服务先保留至 P4 清理调用。

当前进度：P3b 已于 2026-09-14 放行。T06–T09、S03/S04、A2 精确权限、单板块恢复边界及 A0→两个 A2 的真实框架轨迹均已验收；轨迹证明补查和非法卡修正不经过旧单次归因或旧自建循环。最终非 live（含专用 PostgreSQL）为 662 passed、1 skipped、6 deselected，PostgreSQL 标记为 23 passed、646 deselected；Ruff 与 Mypy 通过。该结论不代表 P3、P4 或整个多 Agent 系统完成，下一步进入 P3c。

### P3c：写作与独立审校（M14–M19；A3/A4；T10–T14；S05/S06）

- [x] A3 接管编辑、写作、修订决策；大纲、草稿、修订分别经工具校验并版本化保存。
- [x] A4 独立核验并提交版本绑定报告；程序治理与模型审校分开保存，均不等于人工批准。
- [x] 提炼写作/修订、独立审校方法，保留主体命名和正文无系统标记规则。
- [x] 验证写作→审校退回→修订→当前版本重新审校；最多两轮自动修订、人工并发编辑冲突、已有有效稿不丢失。

放行：父 Agent 能针对审校反馈重新委派研究或写作；完成策略检查实际产物，而非接受模型口头宣告完成。

当前进度：P3c 已于 2026-09-14 放行。T10–T14、S05/S06、A3/A4 精确权限、版本钉住、程序治理、两轮修订上限、SQLite 竞争和真实 A0→A3→A4→A3→A4 框架轨迹均已验收；最终非 live（含专用 PostgreSQL）689 passed、1 skipped、6 deselected，PostgreSQL 标记 26 passed、670 deselected；Ruff 与 Mypy 通过。该结论不代表 P4 或整个迁移完成，下一步进入 P4。

## Phase 4：唯一入口、前端与迁移验收

覆盖 M20/M22/M23/M25–M30；T15–T19 与真实入口联调。保留现有页面视觉和有效功能，不借迁移重做整站。

- [x] 新建分析、定时任务、重试和 CLI 全部接入调度；旧模式参数显式拒绝，旧记录可读。
- [x] 移除前端模式选择，新增任务树/角色/工具/预算，关联板块、证据和审核产物。
- [x] 替换旧固定阶段执行器，保留可以独立复用的业务函数，不仅改 UI 名称。
- [x] 双数据库回归、模拟完整闭环、前端构建及浏览器验收、README 启动文档更新。
- [x] 在明确额度范围内验证真实工具调用能力；不将模拟验收描述为真实服务验收。
- [x] 历史稿件/版本/批准记录保持可读；历史重跑创建带 retry_of 的新根任务，不改写旧运行或伪造任务树。
- [x] fixture/live 数据选择保留，二者均走新框架；显式旧 attribution_mode 返回 422 和迁移提示。
- [x] 验证运行→任务→板块→草稿→审核的双向定位、刷新恢复与旧阶段“未记录”语义。
- [x] 切换前备份数据库并保留可回退部署；回退不让旧引擎接管未完成的新任务。

放行：完整迁移清单 M01–M30 逐项关联验收证据；未验收的功能不得通过删除入口掩盖。所有新建入口确认使用新引擎后，才清理旧 pipeline/归因循环和无调用的旧 Prompt；保留仍供历史查询、导出及领域校验使用的类型与函数。

当前进度：P4 单元 A 已于 2026-09-14 放行。新 `MultiAgentRunService` 和框架 provider 工厂已验证真实 A0→A1、共享模型/Tool 审计、live 写前预检、SQLite 创建/取消/过期接管及专用 PostgreSQL 合同；全量非 live 678 passed、32 skipped，P4 专项（含 PostgreSQL）150 passed，PostgreSQL 标记 27 passed、682 deselected，Ruff 与 Mypy 通过。另以 DeepSeek 官方 `deepseek-flash` 完成临时 SQLite、只读 Tool、¥0.10/60 秒上限的真实框架验收。API/CLI/定时入口尚未切换，下一步进入 P4 单元 B；这不代表 P4 或整个迁移完成。

P4 单元 B 亦已于 2026-09-14 放行：人工候选确认、选择版本与同一 A0 根任务新 attempt 在 SQLite/PostgreSQL 单事务 CAS 中提交；并发只有一方获胜，旧 attempt 迟到调用被拒绝，创建时 `server_default` 策略受服务端约束。专项 54 passed，全量非 live 687 passed、33 skipped，PostgreSQL 标记 28 passed、690 deselected，Mypy 297 个源文件通过。API/CLI/定时入口仍未切换，下一步进入单元 C。

P4 单元 C 的中间记录（已由下述放行结论更新）：新后台命令与 API 适配、retry_of/cancel/live 写前预检、真实 execution_engine 响应和旧 `attribution_mode` 422 迁移错误已完成；`AgentBusinessToolFactory` 已加入并在每次 run 按 `run_id/provider` 校验并复制完整 A1–A4 业务 Tool 注册表。当时全量非 live 689 passed、5 skipped（36 deselected），Ruff 通过，Mypy 302 个源文件通过。

P4 单元 C 已于 2026-09-15 放行：默认 Web/API、新建分析页、定时、重试/取消、历史 data-run generate/retry 与 CLI 已统一接入父子 Agent；旧 data-run 直接新建端点返回迁移错误，旧 `phase1b-draft` 新建命令已移除。历史查询继续与新快照联合返回。最终离线回归 697 passed、19 skipped、36 deselected；PostgreSQL 专用 `_test` 合同 28 passed、724 deselected；前端 245 passed 且构建通过，Ruff/Mypy 通过。下一步进入单元 D；P4 和完整迁移尚未完成。

P4 单元 D/E/F 之详细证据见各自计划与[功能迁移总说明](../specs/2026-09-13-feature-migration-map.md)；此处不再重复。以下记录最终验收单元 G。

**P4 单元 G 已于 2026-09-15 完成。**五项全部完成并验证：

1. **所有新建入口使用新引擎。**以 AST 遍历而非文本搜索证明：旧引擎每个函数的真实调用点唯一且固定在既有老路径，默认接线产出 `MultiAgentRunCommands`/`MultiAgentDataRunWritingService`，调度器实际运行的 bridge 持有 `multi_agent_commands`，生产侧 `build_runtime_dependencies` 的两个调用点都显式传 `enable_multi_agent=True`。反向验证过：改成 `False` 时断言确实失败。
2. **双模式残留清理。**前端已无双模式类型，Prompt 均有存活调用方；删除了 `build_runtime_dependencies` 中休眠的第二套 scheduler/coordinator/bridge（其 bridge 没有 `multi_agent_commands`，即无人使用的旧引擎路径）。历史表、导出与领域校验代码按约束保留。
3. **旧库增量升级与回退步骤。**新增本仓第一个从旧 schema 升级的测试，从 017 之前（该迁移 DROP 并重建 `phase1b_runs`，最易丢数据）起步到最新 34 版；同时记录 `scripts/backup_sqlite.ps1` / `scripts/restore_sqlite.ps1` 与两条限制：SQLite 处于 WAL 模式，直接复制文件可能漏掉 `-wal` 中已提交的数据；PostgreSQL 备份/恢复按设计不在仓库脚本内。
4. **全量验收。**前端单测 259 passed/64 files；生产构建（含 `tsc -b`）通过；浏览器验收 **67 passed / 0 failed**（单元 F 遗留的 3 个失败已逐一定性为断言与自身夹具矛盾并修正）；有界 live Agent 验收 1 passed（¥0.10／3 次调用／12000 tokens／2 次工具／60 秒，工具序列恰为只读的 `inspect_tasks`）。全量离线 743 passed、47 skipped；专用 `sectorpulse_test` **790 passed、0 skipped**（对最终代码重跑，比较类用例同轮对 `sector_pulse_run_comparison_test` 一并通过，0 跳过即全部 PostgreSQL 合同测试确实执行）；Ruff 全通过，Mypy 304 个源文件通过。
5. **文档收尾。**README 已把"归因方式：工作流 / Agent"改写为单一的父子 Agent 执行引擎，说明旧模式参数返回 422、历史运行只读且显示"未记录不等于未执行"；本总计划与迁移表同步更新。

**本次一并修复的两个真实缺陷：**重试历史运行原先返回 500（多 Agent 引擎只能重试自己拥有的运行，历史行无快照可重建），现返回 409 与迁移提示；`retryable` 标志原先对历史运行仍为真，现按"将要执行重试的引擎"清除，不再给出点了就 409 的按钮。

**必须如实记录的一处收窄：**本项第 6 条的"历史重跑创建带 retry_of 的新根任务"在**数据运行**路径上成立（`retry_data_run` 新建根任务并记录 `retry_of`），但在**历史内容运行**（旧 Phase1B）路径上不成立——它被明确拒绝（409 + 迁移提示），而不是伪造。原因是旧 `phase1b_runs.input_json` 里没有多 Agent 所需的 `goal`，而 `create_run` 在缺少 goal 时会把 `"full sector analysis"` 当作目标写入，等于替用户编造了他没有提出的请求。因此这里选择拒绝而非补造，代价是"重试一次旧内容运行"这一动作不再可用，需改为新建运行。

**同时修复了一处硬约束漏洞：**`create_app()` 会把 `.env` 载入进程环境，其中 `SECTOR_PULSE_DATABASE_URL` 指向业务库，而约 27 个合同测试（11 个文件，多数不带 `postgres` 标记）会读取该变量并写行。现新增会话级 autouse 防护：变量未设置则置空，已设置但不以 `_test` 结尾则抛 `BusinessDatabaseRefused`。

至此 M01–M30 的迁移项均已在其所属单元验收，所有新建入口确认使用新引擎，P4 与父子多 Agent 重构完成。未执行提交、合并或推送。
