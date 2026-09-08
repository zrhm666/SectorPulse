# 后端业务分包设计

日期：2026-09-08。基线：main / 6fb4428。用户已批准“保留分层，层内按业务分包”的方向。

## 目标和边界

解决 application、storage、web 顶层文件过度集中问题，让维护者按业务定位代码。首轮只移动模块、更新导入与资源定位、整理测试路径和文档，不重写服务、SQL、模型或算法。

- 保持 Python 3.12+、FastAPI、现有依赖和双数据库运行方式。
- 保持 HTTP URL、请求/响应结构、CLI 命令名、配置项、日志字段与数据库表结构。
- 迁移 SQL 文件及其编号、内容和应用顺序保持不变。
- 不连接或修改业务 PostgreSQL，不创建授权文件，不调用 Live/LLM，不启动后台调度或影子测试。
- 先在隔离工作区执行，当前会话分阶段实施，不用子代理；验收后保留功能分支，合并/推送另行授权。
- 不保留旧模块的空壳转发文件；仓库内导入和 mock 字符串一次同步。Python 内部导入路径会改变，但公共命令和 HTTP 接口不变。仓库外自行编写的直接导入脚本需依迁移表更新。
- 本轮不强行拆分 domain、ports、config、reporting、resources；infrastructure 已有 llm/news/providers 分组，保留。

## 选择

采用层内业务分包。单纯按前缀摆放文件无法修正 SQL 查询错放 application；整体改成垂直业务切片会扩大接口与依赖调整范围。本方案在现有层次中明确归属，避免引入新框架或泛化 service/common 大目录。

## Application 迁移清单

以下旧文件均相对于 `backend/src/sector_pulse/application/`；除分析存储查询外，保留文件名、类名、函数签名。新业务包添加简洁职责说明的 `__init__.py`，不在其中批量导入实现。

| 新包 | 原文件 |
| --- | --- |
| `data_runs/` | `candidate_selection.py`、`candidate_selection_service.py`、`data_run_workbench_queries.py`、`real_data_orchestrator.py`、`real_data_queries.py`、`real_data_writing_bridge.py`、`phase1a2_probe.py` |
| `news/` | `news_ingestion.py`、`news_quality.py`、`news_retrieval.py`、`entity_resolution.py` |
| `writing/` | `agent_validation.py`、`attribution_agents.py`、`attribution_gate.py`、`editorial_agents.py`、`invocations.py`、`phase1b_pipeline.py`、`rewrite_service.py`、`progress.py` |
| `review/` | `evidence_decision_service.py`、`governance_service.py` |
| `runs/` | `run_commands.py`、`run_queries.py` |
| `tasks/` | `run_coordinator.py`、`run_executor.py`、`schedule_service.py`、`scheduled_data_bridge.py`、`scheduler.py`、`task_registry.py`、`task_run_service.py` |
| `comparison/` | `run_comparison_diff.py`、`run_comparison_models.py`、`run_comparison_queries.py` |
| `operations/` | `operations_summary.py` |
| `diagnostics/` | `phase0_probe.py`、`phase1a_probe.py` |
| 移到 `storage/sqlite/review_analytics.py` | `review_analytics.py` |
| 移到 `storage/postgres/review_analytics.py` | `postgres_review_analytics.py` |

已检查：`real_data_orchestrator` 依赖 `phase1a2_probe`，写作桥接依赖 `phase1b_pipeline`，不能仅按 phase 前缀归为废弃探针。保留名称便于追溯；对外 CLI 的 phase 命令继续可用。`progress.py` 是写作管线进度协议，不为单个共享文件额外创建 common 包。

`runs` 明确承载内容运行命令/查询门面，`tasks` 承载任务生命周期与调度；两者不因同有 run 前缀而混在一起。首轮不拆函数，不新增抽象层，不在原本没有关系的业务包之间新增依赖。

## Storage 迁移规则

保留顶层 `database_config.py`、`database_runtime.py`、`runtime_bundle.py`、`ports.py`、`__init__.py` 和 `migrations/`。

- `storage/sqlite.py` → `storage/sqlite/database.py`。
- `storage/postgres.py` → `storage/postgres/database.py`。
- 原顶层 `postgres_*_repository.py` → `storage/postgres/*_repository.py`，去掉文件名中重复的 `postgres_` 前缀。
- 原顶层不带 postgres 前缀的 `*_repository.py` → `storage/sqlite/`，文件名不变。
- `operations_query.py` → `storage/sqlite/operations_query.py`。
- `postgres_operations_query.py` → `storage/postgres/operations_query.py`。
- 两个 review analytics SQL 实现按上表移动，类名保持不变。

例如两种数据库的候选选择实现分别为 `storage/sqlite/candidate_selection_repository.py` 与 `storage/postgres/candidate_selection_repository.py`。不合并两种方言、不改事务边界。storage/runtime_bundle 继续统一装配实现。

数据库模块的默认迁移路径原为 `Path(__file__).parent / 'migrations'`。移动后改为 `Path(__file__).resolve().parents[1] / 'migrations'`，仍指向原 storage/migrations。显式传入 migration_dir 的语义不变。测试验证默认路径发现及原迁移版本，不以“导入成功”代替数据库初始化验收。

## Web 布局

保留 `app.py`、`server.py`、`dependencies.py`、`errors.py`、`__init__.py` 和已有 `routers/`。

- `schemas.py` → `schemas/runs.py`。
- 以下文件进入 `schemas/` 并去掉 `_schemas` 后缀：analytics、data_run、editing、operations、prompt_golden、release_audit、review、shadow、task。
- `data_run_service.py`、`data_run_writing_service.py`、`run_service.py` → `services/`，保留文件名。
- `progress_bus.py` → `events/progress_bus.py`。
- `live_provider.py` → `providers/live_provider.py`。

web/services 保留当前 HTTP 任务适配职责，不借目录整理重写其应用服务边界。应用装配继续位于 dependencies，不将路由反向导入 application。web/schemas 的 `__init__.py` 不转发旧 schemas.py，消费者明确导入 schemas.runs。

## 导入、测试与资源

迁移清单同时用于代码导入、测试 mock/monkeypatch 字符串、脚本、当前维护文档中的可执行示例。逐模块完整路径匹配，不用无边界文本替换 SQL 字符串、HTTP 路径、日志或类名。

单元测试按新业务包归组：application 下对应业务子目录；storage 下分 sqlite/postgres；web 下的 schema/service 专属测试随所属模块调整。集成与合约测试按原场景保留文件位置，更新导入，避免丢失场景覆盖。共享 fixtures 不移动；`test_attribution_gate.py` 的 `Path(__file__).parents[2]` 会因加深一级失效，必须同步定位原 fixture 并单独验证。

新增结构约束测试：application 顶层只保留 __init__.py；规定旧模块文件不存在；新模块可以导入；domain 不因搬迁新增上层依赖。导入检查不初始化数据库或调用网络。PostgreSQL 特有导入验证使用已安装 postgres extra 的测试环境。

扫描 `__file__`、相对 import、动态 import、字符串 patch、脚本路径、包资源，逐一确认是否受移动影响。历史验收记录只追加新的迁移文档链接，不批量改写当时真实路径；README 和新目录规范使用最新路径。

## 实施阶段与验收

1. 建立基线及迁移表，新增结构测试；application 分包，同步消费者。
2. storage 方言包与分析 SQL 归位；核验迁移路径、SQLite 行为及 PostgreSQL 导入/合约边界。
3. web schemas/services/events/providers 分包，整理测试；保留 app/server 入口。
4. 全量回归、打包/启动检查，更新 README 和 `backend/README.md` 目录维护规范，记录未验证边界。

每阶段先运行结构测试观察旧布局失败，再移动对应模块、同步导入，运行针对性行为测试及 Ruff/Mypy，独立提交。最终运行非 Live 后端全量测试、前端测试和构建、隔离 SQLite HTTP 工作流、生产/开发 E2E；检查旧导入残留与迁移 SQL diff 为空。PostgreSQL 只有明确隔离测试库时才运行实库测试，否则记录未执行并保留 CI 合约验证要求，绝不自动使用业务库。

完成标准是目录清楚且所有受影响入口行为保持，不以文件移动数量作为成果。源代码改动中除导入与必要资源定位外出现任何行为变更，必须单独解释、测试，不能混入机械重组。

## 自审结论

39 个 application 顶层 Python 文件中，__init__.py 保留，36 个业务模块进入业务包，2 个分析 SQL 实现进入 storage。storage 的配置、接口、装配和迁移资源留在共同层，SQLite/PostgreSQL 实现按方言对齐。没有删除探针、重建数据库、增加空壳转发、修改 HTTP 或扩展业务功能的任务。
