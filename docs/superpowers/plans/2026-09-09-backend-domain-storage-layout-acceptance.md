# 后端全层目录整理：验收记录

日期：2026-09-09。分支：codex/backend-domain-storage-layout。基线：596ad7d。

## 已实现

- domain 的 19 个模块迁入 market/news/writing/review/runs/evaluation，provider.py 与 llm.py 保留顶层。
- SQLite/PostgreSQL 的 34 个仓库模块迁入同名业务分组，数据库入口、运营聚合查询和迁移 SQL 位置不变。
- 20 个存储协议按业务拆为 8 个模块；消费者使用显式子模块导入，不增加旧路径兼容壳。
- 混合运行/审核路由拆为 runs.py 和 review.py，保留已有工厂签名、路径、标签与注册顺序。
- 同步生产代码、测试导入和字符串 patch；更新根 README 及 backend/README.md。
- config、顶层 ports、reporting、resources 和 infrastructure 分组保持不动。

## 验证证据

| 检查 | 结果 |
| --- | --- |
| 原有结构测试基线 | 5 passed |
| domain 结构/领域测试 | 先观察预期失败，迁移后 44 passed |
| storage 结构/仓库测试 | 先观察 4 项预期失败，迁移后 60 passed |
| 最终包边界测试 | 11 passed，包含禁止导入时联网与 domain 向上依赖检查 |
| 后端非 Live 测试 | 414 passed、14 skipped、24 deselected |
| Ruff | All checks passed |
| 严格 Mypy | 209 source files，无错误 |
| 前端 Vitest | 61 个文件、240 项通过 |
| 前端 TypeScript/Vite 构建 | 通过 |
| 完整 OpenAPI 比较 | 55 个路径的 schema 与路由拆分前一致 |
| 生产语法树比较 | 180 个原有生产模块排除导入后保持一致；20 个协议及 3 个路由相关定义完整一致 |
| SQLite 实际 HTTP 冒烟 | SPA 资源、生成、审核、批准、导出、审计、重试谱系全部通过 |
| Wheel | 隔离构建成功；解包后在仓库外导入 208 个模块、应用 1–18 号 SQLite 迁移、读取 Fixture 资源通过 |
| CLI | sector-pulse --help 成功，原命令保留 |
| SQL/迁移 | 无 diff，无业务数据库迁移 |

14 项 skipped 是未提供 PostgreSQL 连接的测试；24 项 deselected 来自非 Live/非 PostgreSQL 过滤。不把这些计为通过。FastAPI TestClient 产生一条现有依赖弃用警告，不属于目录迁移造成的失败。

## 遇到并处理的问题

- 系统 pytest 临时目录权限不足：使用项目内新的 .tmp-test/layout-* 目录重跑，不修改系统权限或生产配置。
- 拆分文件复制的未使用 import：仅删除未使用 import 并排序，通过 Ruff 和 mypy。
- 临时 Wheel 检查脚本误调用 SQLiteDatabase.close：该类通过上下文管理短连接，没有此方法；更正验证脚本为读取迁移版本，不改生产实现，重跑通过。

## 尚未完成的 PostgreSQL 实库验证

本机 PostgreSQL 服务处于 Running 状态，但 .env 配置的应用账号无 CREATE DATABASE 权限。尝试创建随机命名隔离测试库被服务器拒绝，因此没有创建数据库，也没有运行任何实库测试。

未改用业务库、未扩大账号权限、未更换管理员身份、未执行业务数据清理。待提供专用且名称以 _test 结尾的测试库连接后，再运行 PostgreSQL 仓库测试及 `scripts/verify-runtime-smoke.py --postgres`。

## 交付边界

代码整理及上述离线、SQLite、前端、接口和打包检查完成；PostgreSQL 实库验收仍待必要条件，不宣称全部验收完成。保留当前功能分支，不自动合并或推送。原有内部 Python 导入路径已改变，外部自写脚本需参照设计迁移表更新。
