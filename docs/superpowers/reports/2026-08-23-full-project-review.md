# SectorPulse 前后端完整项目审查

审查日期：2026-08-23

## 结论

Phase 4 功能与技术验收完成，Phase 1–4 的前端主流程和对应后端接口已形成可运行闭环。当前版本适合作为**本机单用户运营工具**使用：Fixture 链路可重复验收，SQLite/PostgreSQL 双运行时可用，React 生产包可由 FastAPI 或 Docker 镜像提供。

本轮没有执行真实数据、真实 LLM 或 20 个交易日影子验收；这些链路继续由 consent、外部 Provider 可用性和用户实际使用触发，不能由自动测试结果替代。最终用户验收仍是交付门槛。

## 审查范围

- React 页面、路由、API client、异步状态、错误反馈、响应式与生产构建。
- FastAPI 路由、草稿所有权、审核/导出状态、SQLite/PostgreSQL 存储适配。
- Docker 镜像、Compose 暴露范围、环境配置和前端静态资源交付。
- 后端单元/集成测试、PostgreSQL 实库测试、前端组件测试、Ruff、Mypy 和敏感文件跟踪检查。

## 本轮修复

### 高优先级

1. 草稿补丁接口原先会先修改草稿，再验证 URL 中的 run 所有权。现先验证 `run_id + draft_id`，错误 run 返回 404 且不会产生新版本。
2. PostgreSQL 发布审计仓储缺少运行时已调用的撤销批准和记录导出实现。现与 SQLite 契约对齐，并通过真实 PostgreSQL 往返测试。
3. Docker 镜像原先没有构建或复制 React 产物。现使用 Node 构建阶段生成 `web/dist`，再复制进 Python 运行镜像；FastAPI 默认提供该 SPA。

### 中优先级

1. 撤销、查询批准、审计和导出接口访问不存在或不属于当前 run 的草稿时，部分路径会返回 500。现统一返回脱敏 404。
2. SPA fallback 原先对未知 `/api/*` 返回 HTTP 200。现保持标准 404，避免监控和客户端把错误路由识别为成功。
3. 审核页批准、撤销、证据决定和退回失败时存在未捕获 Promise；快速切换草稿时旧请求也可能覆盖新选择。现统一显示安全错误反馈，并用请求序列阻止陈旧响应覆盖。
4. Compose 原先将应用和 PostgreSQL 端口暴露到所有网卡。现仅绑定 `127.0.0.1`，符合本机单用户边界；PostgreSQL profile 同时读取 `.env` 中的 LLM/Provider 配置。
5. 项目缺少统一启动说明。现新增根目录 README，覆盖 `.venv`、前后端开发/生产启动、SQLite/PostgreSQL、Fixture/Live consent 与 Docker 流程。

## 验证证据

- 后端默认回归：`203 passed, 21 skipped`，35.11 秒。
- PostgreSQL 实库仓储回归：`15 passed`，8.67 秒；未清空或重建用户数据库。
- 前端组件回归：`51 passed`，27 个测试文件。
- 前端生产构建：TypeScript 与 Vite 成功，79 个模块，主 JS gzip 70.85 kB。
- Python lint：`ruff check backend/src backend/tests` 通过。
- Compose 静态解析：`docker compose ... config --quiet` 通过；Docker Desktop daemon 未运行，因此未执行实际镜像构建和容器健康检查。
- Phase 4 浏览器验收：Fixture 创建、草稿 v2、证据 KEEP、批准、JSON 导出、调度保存、只读影子页及 390px 响应式均通过。
- 跟踪文件检查：未发现密码 `200252`、TODO/FIXME/NotImplementedError；仅 `.env.example` 被 Git 跟踪，真实 `.env`、consent 和运行数据未跟踪。

## 已知剩余风险

1. **严格类型检查未通过。** `mypy backend/src` 报告 32 个文件共 186 个错误，主要集中在 SQLite row 解码、PostgreSQL 可选 engine、运行时仓储 bundle 使用 `object` 以及服务接口缺少 Protocol。自动测试覆盖了当前行为，但后续重构前应单独安排“存储端口类型化”阶段。
2. **Live 链路未在本轮执行。** 真实行情/新闻、真实 LLM 与额度消耗测试受 consent 和外部服务约束；Fixture 成功不代表外部 Provider 当前可用。
3. **Docker 未做运行时验收。** Compose 配置和 Dockerfile 契约测试通过，但本机 Docker daemon 未启动，尚未确认实际 build、healthcheck 和持久卷恢复。
4. **浏览器自动 E2E 较弱。** 当前 Playwright smoke 只验证基本页面文本；复杂审核闭环依靠本轮人工浏览器验收和组件测试。建议后续把 Fixture 审核闭环固化为 Playwright 测试。
5. **依赖弃用提示。** Starlette TestClient 当前提示未来迁移到 `httpx2`，不影响现有功能，但升级 FastAPI/Starlette 时需要处理。
6. **安全边界是本机单用户。** 项目没有账号认证和多租户权限模型；当前通过 loopback 绑定限制访问，不应直接暴露到公网。

## 建议后续顺序

1. 日常使用 Fixture/Live 流程，记录真实 Provider 或业务规则问题。
2. 启动 Docker Desktop 后补跑镜像构建、两个 Compose 模式与重启恢复验收。
3. 将 PostgreSQL/SQLite 仓储抽象为显式 Protocol，逐步清零 Mypy 错误。
4. 把浏览器 Fixture 审核闭环纳入 Playwright，并在依赖升级时处理 TestClient 弃用提示。
