# 2026-09-06 前端工具链与开发模式验收

## 结论

开发工具链升级、StrictMode 请求与自动保存修复、完整非 Live 质量门槛通过。2026-09-06 的全量 npm 审计和生产依赖审计均为 0 个已知漏洞；这是本次扫描结果，不代表不存在未知漏洞。

本轮不改变页面视觉、业务 API、数据库结构或用户配置。业务 PostgreSQL 未用于测试，未调用 Live 数据或真实 LLM，未恢复影子测试。

## 版本与配置

| 项目 | 验收状态 |
| --- | --- |
| Node / npm | 本机 24.17.0 / 11.13.0；package engines 为 `^22.22.2 \|\| ^24.15.0 \|\| >=26.0.0`，与现有 jsdom 要求对齐 |
| Vite | 5.4.21 → 8.2.2，锁文件固定；Vitest 与 React 插件共用同一版本 |
| React 插件 | 4.7.0 → 6.1.1；使用 Oxc，不额外启用 React Compiler |
| React / Vitest | 保持 18.3.1 / 4.1.10 |
| JS 转译目标 | 保留 `es2020, edge88, firefox78, chrome87, safari14`；不等于所有旧浏览器 API 均已验收 |
| 本机开发地址 | 默认仅绑定 `127.0.0.1`；`/api` 仍代理至 9000 |
| 依赖树 | `npm ls --all` 退出 0；旧无效 esbuild peer 已移除。可选平台包/未使用插件显示 UNMET OPTIONAL，不是必需依赖缺失 |

## 先失败、再修复的证据

1. 工具链测试使用真实 Vite HTTP 服务、随机回环端口和合成 `.env`，不读取真实密钥。旧 Vite 在 Windows `/.env::$DATA?raw` 返回 200，而预期 403：3 通过、1 失败；升级后 TSX、代理路径/参数、普通 `.env` 和 Windows 路径边界 4 项全部通过。该路径风险见 [Vite 官方公告](https://github.com/vitejs/vite/security/advisories/GHSA-fx2h-pf6j-xcff)。
2. 总览复用已取消请求，以及旧工作台请求结束新请求的加载状态：新用例在旧代码下 3 失败/13 通过，修复后 16 通过。清理时释放请求，异步成功、失败和收尾均核对当前请求身份。
3. 审核队列过早结束加载、自动保存重挂载后不再更新输入/保存状态：旧代码 4 失败/8 通过，修复后 12 通过。新增测试覆盖保存成功、失败、版本冲突时保留文本与正确状态。

浏览器检查最初仅对生产构建执行，未触发 StrictMode effect 重放。本轮增加 `npm run test:e2e:dev`，不关闭 StrictMode。只有显式开发测试允许 GET 的精确 `net::ERR_ABORTED`，生产模式仍拒绝所有失败请求；HTTP 错误、其他网络失败、未处理接口及页面异常都保留检查。

开发测试还揭示审核多状态夹具移除路由的短暂空窗，GET 曾落至未启动的 9000，返回 502。修复为 context 级兜底拒绝真实 API、页面夹具无缝替换；未通过忽略 502 达标，也未连接业务数据库。

## 完整质量结果

在隔离工作区使用主目录 `.venv` 执行 `scripts/verify-stage0.ps1`，最终退出码 0。

| 检查 | 结果 |
| --- | --- |
| Ruff / Mypy | 通过 / 163 个源文件通过 |
| Python 依赖审计 | 0 个已知漏洞 |
| 非 Live 后端 | 343 通过，22 个 PostgreSQL 用例跳过，7 个 Live 用例排除 |
| 工具链真实 HTTP 边界 | 4 通过，包含 Windows 专项 |
| 前端单测 | 50 文件、185 项通过（新增 7 项） |
| 生产浏览器 | 40 通过，12.1 秒 |
| 开发浏览器 | 同一组 40 项通过，25.0 秒；不是 80 个不同业务用例 |
| 真实 HTTP + SQLite | 构建资源、API、Fixture 生成、审核、批准、导出、审计、重试来源 8 项通过 |
| 完整依赖树 / 全量 npm 审计 | 通过 / 0 个已知漏洞 |
| 独立生产依赖审计 | 0 个已知漏洞 |

生产构建包含 103 个模块：`index-D4tmq5eV.css` 56.75 kB / gzip 10.30 kB；`index-BVHE89TK.js` 321.05 kB / gzip 97.84 kB。转换链变化产生新的构建资源；没有重构视觉或放宽业务断言。

本地脚本与 CI 均新增工具链边界、开发浏览器和完整依赖树检查；npm 审计不再省略开发依赖。Starlette/httpx 弃用及终端颜色提示仍存在，不影响本轮检查；未借机升级无关组件。

## 本地集成

- 设计计划提交：`f34ae92`。
- 工具链及边界测试：`87448c8`。
- 请求、自动保存和开发浏览器修复：`b7f8bc0`。
- 质量门槛与验收记录：`c9cc456`。
- 主目录 `main` 已由 `bbafb17` 快进至 `c9cc456`；保留工作分支和隔离工作区，未推送远端。
- 主目录 `web` 按锁文件重新安装后，4 项工具链测试、生产构建、完整依赖树及全量 npm 审计再次通过；主目录 `.venv` 的真实 HTTP + 临时 SQLite 八项流程再次通过。
- 两处构建资源名称及 SHA-256 完全一致：CSS `63ac90ead68a8fb5f4a3e5fcd26770ab251858e3483fbee39cb7b181912cf58b`；JS `05f4061754d60b28618d8c77534c6ea9bbfeeeed2baeceba020f6aaad7ada12c`。此最终状态以随后文档提交补充，不改变已验证的应用代码。

## 验收边界与复验入口

本轮未重跑 PostgreSQL 专项、容器构建、真实上游或远端 CI。双数据库与本机业务库升级的证据见 [此前可靠性验收](2026-09-05-reliability-closeout.md) 和 [本机业务 PostgreSQL 验收](2026-09-06-business-postgresql-upgrade.md)。Docker 为可选，不是本机运行前提。

```powershell
# 根目录：完整非 Live 验收
powershell -ExecutionPolicy Bypass -File scripts/verify-stage0.ps1

# web 目录：前端单独复验
npm.cmd ci
npm.cmd run test:tooling
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e
npm.cmd run test:e2e:dev
npm.cmd ls --all
npm.cmd audit
```

浏览器测试自行启动并关闭 4173 端口服务，需要该端口空闲；不必启动日常业务后端。
