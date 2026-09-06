# Web Toolchain Security Implementation Plan

> **For agentic workers:** Use executing-plans inline, as explicitly requested; no subagents, no per-phase approval.

**Goal:** 修复开发依赖安全和兼容缺口，并让全量依赖检查成为交付门槛。

**Architecture:** 保持现有 React SPA 与 FastAPI 静态交付，统一构建/测试使用 Vite 8，通过原生 Node 测试驱动真实 Vite HTTP 服务验证边界。

**Tech Stack:** Vite 8.2.2、React 插件 6.1.1、Vitest 4.1.10、Node 22.22.2 / 24.15.0 以上对应支持版本、Playwright。

**Spec:** `docs/superpowers/specs/2026-09-06-web-toolchain-security-design.md`

## Global Constraints

- Node engines：`^22.22.2 || ^24.15.0 || >=26.0.0`；开发/预览仅默认绑定 `127.0.0.1`。
- JS target：`['es2020', 'edge88', 'firefox78', 'chrome87', 'safari14']`；API 代理仍为 9000。
- 使用已有工作区 `.worktrees/stage0-reliability`、主目录 `.venv`；npm 使用工作区 `web/.npm-cache` 避免全局缓存权限问题。
- 不改数据库、业务页面布局、业务 API、生产依赖或用户配置；不推送、不调用 Live。开发模式补充发现仅允许下述请求生命周期修复。

## Task 1：真实开发服务器边界测试与依赖升级

**Files:** 新增 `web/tooling/vite-runtime.test.mjs`；修改 `web/package.json`、`web/package-lock.json`、`web/vite.config.ts`、`README.md`。

**Interfaces:** `npm run test:tooling` 执行 `node --test tooling/*.test.mjs`；测试调用项目 Vite `createServer`，随机回环端口和合成 `.env` 夹具，结束后关闭服务、删除本次创建的临时目录。

- [x] 使用 Node `test`、`assert`、真实 `createServer` 建立测试：TSX 端点返回编译后的 JavaScript；`/api/health?probe=1` 经代理保留路径和参数；普通 `.env` 及 Windows `/.env::$DATA?raw` 返回拒绝状态且不含公开夹具标识 `sectorpulse-public-probe`。不使用真实项目 `.env`。
- [x] 在旧依赖运行 `node --test tooling/*.test.mjs`，Windows 测试复现 200 而非 403（3 通过/1 失败）；审计 2 个告警，依赖树显示无效 esbuild peer。修复夹具服务关闭顺序后稳定复现。
- [x] 修改 package 中 Vite 为 `^8.2.2`、React 插件为 `^6.1.1`，增加 engines 和 `test:tooling`。执行 `npm.cmd install --cache .npm-cache` 更新锁文件，不使用 `--force` 或 `--legacy-peer-deps`。
- [x] Vite config 增加 `build: { target: ['es2020', 'edge88', 'firefox78', 'chrome87', 'safari14'] }`、`server.host: '127.0.0.1'`、`preview: { host: '127.0.0.1' }`。保留业务 test 设置和 proxy，新增 tooling 目录排除，避免 Vitest 接管 Node 测试。
- [x] README 修改 Node 要求，写明 `npm ci`、开发服务只限本机。4 项工具链测试、178 项前端单测、40 项生产浏览器测试、构建、全量审计、依赖树均通过；实现提交 `87448c8`。全量审计使用说明随 Task 2 门槛更新。

## Task 2：交付门槛与本地集成

### 开发模式补充修复（整体验收中发现）

- [x] 为 `useOperationsSummary` 增加 StrictMode 取消后重新加载、旧响应不覆盖/结束新请求的回归；为 `useDataRunWorkbench` 增加旧运行请求收尾不干扰新运行的回归。旧代码 3 失败/13 通过，修复后 16 通过。
- [x] 清理时释放已取消的请求；只有当前请求可更新数据、加载状态和轮询计划。保留 StrictMode 与原轮询间隔。
- [x] 开发回归补充：审核队列取消请求不能提前结束加载；自动保存重挂载后恢复 mounted 标记，编辑文本和成功/失败/冲突状态可见。旧代码 4 失败/8 通过，修复后 12 通过。
- [x] 浏览器 runner 增加显式开发模式；仅该模式允许 GET `net::ERR_ABORTED`，保留生产模式原严格错误检查。开发模式 40 项通过，已加入本地/CI 门槛；生产模式随下方完整回归复验。

测试夹具补充修复：审核多状态测试移除路由时曾让 GET 落到无服务的 9000 并返回 502。现在默认 API 保护放在 browser context，不随页面路由替换而消失；状态切换保留旧夹具至新夹具接管，不留下真实后端访问窗口。该失败没有过滤，修复后开发浏览器 40 项通过。

**Files:** 修改 `scripts/verify-stage0.ps1`、`.github/workflows/quality.yml`；新增 `docs/superpowers/acceptance/2026-09-06-web-toolchain-security.md`；更新原收尾计划和历史验收指针。

**Interfaces:** 全量质量脚本沿用原启动方式；新增 `npm run test:tooling` 和 `npm ls --all`，把 `npm audit --omit=dev` 改为 `npm audit`，任一非零退出都失败。

- [x] 本地脚本在前端单测前执行工具链测试，依赖审计处执行 `npm ls --all` 及全量 `npm audit`；CI 添加相同步骤。
- [x] 运行 `powershell -ExecutionPolicy Bypass -File scripts/verify-stage0.ps1 -PythonPath D:\work\SectorPulse\.venv\Scripts\python.exe`，最终退出 0：343 后端、185 前端、4 工具链、40 生产/40 开发浏览器、实际 SQLite HTTP、依赖树与全量审计均通过。业务 PostgreSQL 不用于测试。
- [x] 验收文档记录实际版本、测试数量、构建资源、全量/生产审计以及未执行的 Live/Docker/远端 CI 范围；勾选原收尾计划的开发依赖待办。
- [ ] `git diff --check`、当前会话审查后提交；main 干净时 `git merge --ff-only codex/stage0-reliability`，不拉远端、不推送。
- [ ] 主目录 `web` 执行 `npm ci --cache .npm-cache`、工具链测试、构建和全量审计；主目录 `.venv` 执行 `scripts/verify-runtime-smoke.py` 默认临时 SQLite，确认已构建资源与真实接口可用。
