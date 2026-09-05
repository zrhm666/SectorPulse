# 2026-09-05 可靠性收尾验收

## 结论

代码修复、SQLite 与隔离 PostgreSQL 18.6 验证通过。本机使用 `.venv` + PostgreSQL，不需要 Docker。
本机业务服务 `postgresql-x64-18` 仍停止，当前 Windows 用户无法打开服务进行启动；业务库备份和升级尚未执行。不能将临时数据库验收等同于业务库已升级。

## 已完成修复

| 项目 | 行为与证据 |
| --- | --- |
| 调度异常恢复 | 派发、推进分别隔离异常；后续轮询继续，系统状态反映最近循环健康。回归覆盖故障后恢复、派发故障时推进手动工作、关闭已失败后台任务。 |
| 内容页终态 | INTERRUPTED、UNREVIEWED、REVISE_REQUIRED 均结束监听；切换运行清除旧状态，历史终态不再打开 SSE。 |
| 重试来源 | 数据与内容重试创建时保存 retry_of_run_id；原记录保留，立即取消也保存来源。详情接口提供来源 ID。 |
| 数据库迁移 | 前向迁移 018_content_retry_lineage，SQLite/PostgreSQL 都支持；旧记录默认来源为空。 |
| 可选容器配置 | Live 覆盖文件只读挂载授权文件；SQLite 服务清空继承的数据库 URL；Compose 配置校验通过。 |
| 实际 API 验收 | 新增 scripts/verify-runtime-smoke.py，通过本机真实 HTTP 服务验证构建资源、生成、审核、批准、导出、审计和重试来源；加入本地质量脚本及 CI。 |

## 本轮验证结果

| 检查 | 结果 |
| --- | --- |
| Ruff | 后端通过 |
| 严格 Mypy | 163 个源文件通过 |
| Python 依赖审计 | 未发现已知漏洞 |
| 非 Live 后端测试 | 343 通过，22 PostgreSQL 用例在常规门禁跳过，7 Live 用例排除 |
| 独立 PostgreSQL 专项 | 39 通过，包括上述 22 实库用例及 17 同步仓储契约检查；不与后端总数简单相加 |
| 前端单测 | 50 文件、178 项通过 |
| 浏览器测试 | 40 项通过，使用受控接口响应 |
| 生产构建 | 116 模块，CSS 56.94 kB / gzip 10.31 kB，JS 303.90 kB / gzip 97.71 kB |
| npm 生产依赖审计 | 0 漏洞 |
| 实际 HTTP + SQLite | 构建资源、内容生成、审核、批准、导出、审计、重试来源通过 |
| 实际 HTTP + PostgreSQL | 同样八项流程通过，使用 Fixture LLM |
| PostgreSQL 17→18 升级 | 独立旧结构数据库保存草稿和输入后升级，内容保留且新增来源字段为空 |
| PostgreSQL 备份恢复 | 专用测试库 custom-format 导出成功；归档 179 TOC 条目；恢复至另一专用库后版本 18 与重试来源记录存在 |

PostgreSQL 测试使用本机安装的 `D:\software\postgresql18\bin`，不是 Docker。
临时实例地址为 `127.0.0.1:55439`，用户 `sectorpulse_test`；测试库 `sectorpulse_closeout_test`、`sectorpulse_restore_test`、`sectorpulse_upgrade_test`。
实例及备份保留在开发工作区 `.tmp/closeout-pg-3e2219f7/`，不进入 Git；服务当前未监听该端口。

## 验收范围与未完成项

- 业务数据库 `sectorpulse_runtime` 的备份、迁移与启动验收：等待本机 PostgreSQL 服务启动；本轮没有清空、迁移或写入该业务库。
- Docker 引擎未启动：只完成配置解析，未执行容器构建/启动；这是可选部署，不阻塞本机使用。
- 外部 Live 行情、新闻与真实 LLM：本轮没有调用，不声称真实上游链路已验收。
- 20 日影子测试继续按用户要求暂停。
- CI 已配置检查，未推送远端，因此没有本轮远端 CI 执行结果。
- Starlette/httpx 与 Vite 转换插件仍有上游弃用警告，未影响本轮检查。

## 复验

```powershell
# 全部常规检查，包含实际 SQLite HTTP 流程
powershell -ExecutionPolicy Bypass -File scripts/verify-stage0.ps1

# 已构建前端时，单独验证 SQLite；自动创建并清理临时数据库
.\.venv\Scripts\python.exe scripts/verify-runtime-smoke.py

# PostgreSQL 只允许显式指定的专用测试库，名称以 _test 结尾
$env:SECTOR_PULSE_TEST_DATABASE_URL='postgresql+psycopg://测试用户:密码@127.0.0.1:5432/专用库_test'
.\.venv\Scripts\python.exe scripts/verify-runtime-smoke.py --postgres
```

## 集成记录

工作分支：`codex/stage0-reliability`。本轮实现提交：`740d009`（设计计划）、`f8ebb28`（调度）、`b5465bd`（终态）、`28a4312`（重试来源）、`841b7a7`（可选部署）。
本地 main 集成与主目录重建在最终检查后记录；不推送远端。
