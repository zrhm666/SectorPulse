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
- 不改数据库、业务页面、生产依赖或用户配置；不推送、不调用 Live。

## Task 1：真实开发服务器边界测试与依赖升级

**Files:** 新增 `web/tooling/vite-runtime.test.mjs`；修改 `web/package.json`、`web/package-lock.json`、`web/vite.config.ts`、`README.md`。

**Interfaces:** `npm run test:tooling` 执行 `node --test tooling/*.test.mjs`；测试调用项目 Vite `createServer`，随机回环端口和合成 `.env` 夹具，结束后关闭服务、删除本次创建的临时目录。

- [ ] 使用 Node `test`、`assert`、真实 `createServer` 建立测试：TSX 端点返回编译后的 JavaScript；`/api/health?probe=1` 经代理保留路径和参数；普通 `.env` 及 Windows `/.env::$DATA?raw` 返回拒绝状态且不含公开夹具标识 `sectorpulse-public-probe`。不使用真实项目 `.env`。
- [ ] 在旧依赖运行 `node --test tooling/*.test.mjs`，记录 Windows 保护回归失败；运行 `npm audit --json` 和 `npm ls --all` 记录问题。新增测试必须先失败再升级。
- [ ] 修改 package 中 Vite 为 `^8.2.2`、React 插件为 `^6.1.1`，增加 engines 和 `test:tooling`。执行 `npm.cmd install --cache .npm-cache` 更新锁文件，不使用 `--force` 或 `--legacy-peer-deps`。
- [ ] Vite config 增加 `build: { target: ['es2020', 'edge88', 'firefox78', 'chrome87', 'safari14'] }`、`server.host: '127.0.0.1'`、`preview: { host: '127.0.0.1' }`。保留 test 设置和 proxy。
- [ ] README 修改 Node 要求，写明 `npm ci`、全量审计与开发服务只限本机。运行 `npm run test:tooling`、`npm test -- --run`、`npm run build`、`npm run test:e2e`、`npm audit`、`npm ls --all`，全部通过后提交任务。

## Task 2：交付门槛与本地集成

**Files:** 修改 `scripts/verify-stage0.ps1`、`.github/workflows/quality.yml`；新增 `docs/superpowers/acceptance/2026-09-06-web-toolchain-security.md`；更新原收尾计划和历史验收指针。

**Interfaces:** 全量质量脚本沿用原启动方式；新增 `npm run test:tooling` 和 `npm ls --all`，把 `npm audit --omit=dev` 改为 `npm audit`，任一非零退出都失败。

- [ ] 本地脚本在前端单测前执行工具链测试，依赖审计处执行 `npm ls --all` 及全量 `npm audit`；CI 添加相同步骤。
- [ ] 运行 `powershell -ExecutionPolicy Bypass -File scripts/verify-stage0.ps1 -PythonPath D:\work\SectorPulse\.venv\Scripts\python.exe`，核对完整结果。业务 PostgreSQL 不用于测试。
- [ ] 验收文档记录实际版本、测试数量、构建资源、全量/生产审计以及未执行的 Live/Docker/远端 CI 范围；勾选原收尾计划的开发依赖待办。
- [ ] `git diff --check`、当前会话审查后提交；main 干净时 `git merge --ff-only codex/stage0-reliability`，不拉远端、不推送。
- [ ] 主目录 `web` 执行 `npm ci --cache .npm-cache`、工具链测试、构建和全量审计；主目录 `.venv` 执行 `scripts/verify-runtime-smoke.py` 默认临时 SQLite，确认已构建资源与真实接口可用。
