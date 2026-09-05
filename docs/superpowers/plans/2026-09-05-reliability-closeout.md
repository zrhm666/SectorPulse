# Reliability Closeout Implementation Plan

> **For agentic workers:** Use executing-plans inline as requested. Track each task below; do not dispatch subagents or ask for per-phase approval.

**Goal:** 修复 2026-09-05 审查缺口，形成可复核的双数据库与本地交付证据。

**Architecture:** 复用现有嵌入式调度器、存储协议和 React 状态组件。新增最小前向迁移，保持现有 API 向后兼容。

**Tech Stack:** Python 3.12、FastAPI、SQLite、同步 psycopg、React 18、TypeScript、Vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-09-05-reliability-closeout-design.md`

## Global Constraints

- 在 `.worktrees/stage0-reliability` 开发；Python 使用主目录 `.venv`，PYTHONPATH 指向工作区 backend/src。
- 非 Live 测试使用独立临时 SQLite；PostgreSQL 必须使用专用测试库。
- 不清空业务库、不恢复影子测试、不推送远端；成功标准未满足时不声称已完成。
- 只添加捕获实际行为缺陷的回归测试，文档和低风险配置通过检查与执行验证。
- 用户使用本机 PostgreSQL，Docker 为可选部署；代码合入门槛采用已经通过的独立 PostgreSQL 测试，业务库升级单列部署待办。

## Task 1：调度恢复与健康状态

**Files:** `backend/src/sector_pulse/application/scheduler.py`、`web/routers/operations.py`、`web/app.py`；测试 `backend/tests/unit/application/test_scheduler.py` 和现有 operations API 测试。

**Interfaces:** `EmbeddedScheduler.is_running -> bool`、`is_healthy -> bool`；operations readiness 使用实际后台任务健康状态。

- [x] 在 scheduler 测试增加一次推进异常后下一轮成功、派发异常不阻塞推进、降级/恢复及关闭已失败任务的用例。核心断言：
  ```python
  embedded.start()
  await asyncio.wait_for(recovered.wait(), timeout=1)
  assert embedded.is_running
  assert embedded.is_healthy
  await embedded.stop()
  assert not embedded.is_running
  ```
- [x] 运行 `python -m pytest backend/tests/unit/application/test_scheduler.py -q`，确认新用例失败。
- [x] 将 `_loop` 中派发、推进分别 try/except Exception；仅记录阶段和异常类型。通过 `_healthy` 记录本轮结果，`is_running` 检查 Task 未 done。`stop` 收集已经失败 Task 的异常，lifespan 用 finally 释放资源。
- [x] 运行 scheduler、operations 和 startup recovery 测试，确认恢复及接口状态。
- [x] 提交 `fix: recover scheduler cycles and report actual health`（f8ebb28）。

## Task 2：内容终态与订阅生命周期

**Files:** `web/src/useRuns.ts`、`web/src/useRuns.test.tsx`、`web/src/pages/RunDetailPage.tsx`、`web/src/pages/RunDetailPage.test.tsx`。

**Interfaces:** hook 保持 `{events, done, error}`；终态快照结束监听，runId 变化重置状态。

- [x] 参数化历史 INTERRUPTED/UNREVIEWED/REVISE_REQUIRED 测试；断言 `done===true` 且不创建 SSE，增加从旧终态切换新 RUNNING 的用例。
- [x] 运行 `npm.cmd test -- src/useRuns.test.tsx --run`，确认失败。
- [x] 补全终态集合，effect 开始清空状态，异步回调检查 disposed；内容页添加中断和审核未完成说明，保留已有重试入口。
- [x] 运行 hook 和 RunDetailPage 测试及 TypeScript 构建。
- [x] 提交 `fix: align content terminal states and stream lifecycle`（b5465bd）。

## Task 3：数据与内容重试来源持久化

**Files:** `backend/src/sector_pulse/web/data_run_service.py`、`web/run_service.py`、`web/schemas.py`、`application/real_data_orchestrator.py`、`application/real_data_queries.py`、`storage/phase1b_runs_repository.py`、`storage/postgres_phase1b_runs_repository.py`；新建 `storage/migrations/018_content_retry_lineage.sql`。

**Interfaces:** `DataRunService.create(..., *, retry_of_run_id: UUID | None = None)`；`run_real_data_workflow(..., retry_of_run_id: UUID | None = None)`；`RunService.create_run(..., *, retry_of_run_id: UUID | None = None)`；Phase1BRunRow/RunSummary 增加可空来源。

- [x] 通过真实 SQLite 服务运行失败/结束样例后重试，读取新记录并断言来源等于旧 ID，旧记录和输入不变；为 PostgreSQL 仓储增加来源往返断言。
- [x] 运行新用例，确认缺失来源导致失败。
- [x] 018 使用 `ALTER TABLE phase1b_runs ADD COLUMN retry_of_run_id TEXT; CREATE INDEX idx_phase1b_runs_retry_of ON phase1b_runs(retry_of_run_id);`，两数据库共同适用。更新插入、读取、接口序列化与真实数据工作流参数传递。取消立即发生时也保留来源。
- [x] 更新迁移头预期并运行存储、运行服务、real data 和 API 测试；确认旧记录迁移安全。
- [x] 提交 `fix: persist data and content retry lineage`（28a4312）。

## Task 4：部署配置闭环

**Files:** 新建 `docker-compose.live.yml`；修改 `docker-compose.yml`、`README.md`、`.dockerignore`。

- [x] 基础 SQLite 服务设置 `SECTOR_PULSE_DATABASE_URL: ""`。
- [x] Live 覆盖文件为两个应用服务增加只读 bind 授权文件，`bind.create_host_path: false`。排除工作区和包缓存进入 Docker context。
- [x] Compose `config --no-interpolate --no-env-resolution --quiet` 验证通过；Docker 引擎未运行，未构建容器。用户本机部署无需 Docker。
- [x] README 写明创建授权文件的含义、基础 Fixture 与 Live 覆盖启动方式；提交 `fix: complete opt-in live container configuration`（841b7a7）。

## Task 5：数据库与实际 API 验收

**Files:** 新建 `docs/superpowers/acceptance/2026-09-05-reliability-closeout.md`，必要时添加可复用验收脚本至 scripts。

- [x] 只读确认 PostgreSQL 服务、连接目标与数据库名；尝试启动已安装服务，Windows 服务管理器拒绝访问。
- [ ] 业务库执行 custom-format pg_dump 并用 pg_restore --list 验证；日志不得包含密码。
- [x] 独立 PostgreSQL 18.6 实例执行 39 项契约及集成测试，迁移头 018；专用库备份恢复及 17→18 旧数据保留验证通过，业务库未用于测试。
- [x] 使用临时 SQLite 和 PostgreSQL 启动实际 FastAPI 并通过 HTTP 验证 Fixture 创建、完成、草稿、审核/导出；结果通过。
- [x] 运行 `scripts/verify-stage0.ps1 -PythonPath D:\work\SectorPulse\.venv\Scripts\python.exe`，343 后端、178 前端、40 浏览器测试通过，审计无漏洞。

## Task 6：文档、审查与本地集成

- [x] 修正旧验收记录的不准确重试来源描述，链接本轮实现和证据；更新 README migration head。
- [ ] 当前会话审查全部差异；运行 `git diff --check`，提交验收文档。
- [ ] 本地门槛全部通过后确认 main 干净，执行 `git merge --ff-only codex/stage0-reliability`。
- [ ] 主目录构建前端并确认 main 提交和 dist 一致，保留分支以便追踪；不推送。
- [ ] 若必要环境仍阻塞，记录准确待办，保留已提交成果，说明阻塞原因与继续条件。
