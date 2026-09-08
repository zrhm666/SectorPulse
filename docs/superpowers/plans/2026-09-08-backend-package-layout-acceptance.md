# 后端业务分包验收

日期：2026-09-08

- 基线：949fe92（main）。
- 工作分支：codex/backend-package-layout。
- 执行位置：D:/work/SectorPulse/.worktrees/backend-package-layout。
- 依据：[设计](../specs/2026-09-08-backend-package-layout-design.md)、
  [执行计划](2026-09-08-backend-package-layout.md)。

## 完成内容

89 个生产模块搬迁：application 的36个业务模块进入9个业务包；
38个存储/分析模块进入双方言目录；15个 Web 模块按职责分包。
SQL analytics 从 application 移到 storage，类名与接口不变。
测试同步分组，集成与合约测试保留原场景。

SQLite/PostgreSQL 的默认迁移路径改为从 database.py 上溯到 storage/migrations；
显式 migration_dir 保持原语义。共享 fixtures 保持原位置，归因测试修正路径深度。
全仓消费者和 mock 路径同步，不留旧模块转发壳。

根 README 已更新，新增 [后端维护指南](../../../backend/README.md)，包入口写明职责。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 改动前离线后端基线 | 400 passed，14 skipped，24 deselected |
| 最终离线后端全量 | 408 passed，14 skipped，24 deselected |
| 最后单独复核结构/迁移边界 | 8 passed |
| Ruff（backend、scripts） | 通过 |
| Mypy | 185 个源文件通过 |
| 前端 Vitest | 230 passed |
| 前端 tooling | 4 passed |
| TypeScript + Vite 生产构建 | 通过 |
| 生产浏览器 E2E | 61 passed |
| 开发浏览器 E2E | 61 passed |
| 临时 SQLite 真实 HTTP smoke | 通过 |
| wheel 构建及资源检查 | 89个新模块路径齐全，全部迁移 SQL 字节一致 |
| 全新 wheel 进程 | 181个模块导入，禁用网络连接，SQLite 1—18迁移成功 |
| 原生产模块 AST 对比 | 167个模块除导入及两处默认资源定位外一致 |
| SQL、domain、前端源码及 CI 差异 | 空 |
| git diff --check | 通过 |

真实 HTTP smoke 覆盖生产 SPA 静态资源、Fixture 生成、审核、批准、
Markdown 导出、审计和重试血缘，不连接业务库。
浏览器 E2E 使用受控接口响应，与真实 HTTP smoke 的覆盖边界不同。

新增测试包括 application/storage/web 目录边界、模块导入、domain 依赖、
SQLite 默认迁移幂等性、PostgreSQL 默认资源发现与显式目录覆盖。
PostgreSQL 资源测试使用记录 SQL 的隔离替身，不冒充服务器执行验证。

## 发现和处理

- 结构测试在旧布局下失败，搬迁后通过。
- 补齐一处从 application 包直接导入模块的测试，以及共享 Web 测试模块的消费者路径。
- 较长 mock 路径换行，导入顺序由 Ruff 整理。
- 首次无构建隔离打包因当前 .venv 没有 hatchling 失败；
  使用标准隔离构建成功，未更改项目依赖或主工作区虚拟环境。
- 保留既有 Starlette/httpx 弃用提示，本轮没有升级依赖。

## 安全边界与未验证部分

- 未执行 PostgreSQL 实库测试；14项因无隔离连接跳过，
  Live/Live LLM/PostgreSQL 标记的24项被排除。已有 CI PostgreSQL 合约任务保留，
  本轮尚未推送，不能声称远端 CI 已通过。
- 未连接或修改用户 PostgreSQL，未创建授权文件，未调用真实行情/新闻或付费 LLM，
  未运行影子测试或业务调度。
- 只改变内部 Python 导入路径；外部自写脚本需要按设计迁移表适配。
- 这不是全架构重写；原有服务耦合和大文件拆分仍属后续独立任务。
- 功能分支保留，不合并、不推送；主工作区仍是 main。

## 复核结论

按用户要求在当前会话自审，未使用子代理。
目录边界、资源定位、行为兼容、打包和前后端联动验证完成。
本轮分包任务可交付；上述 PostgreSQL 实库验证限制必须随交付保留。
