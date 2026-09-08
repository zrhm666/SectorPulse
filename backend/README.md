# 后端目录与维护指南

SectorPulse 后端保留分层架构，在层内按业务组织模块。目录整理不改变 HTTP API、CLI、数据库表或运行配置。

## 从哪里找代码

```text
src/sector_pulse/
├── application/
│   ├── data_runs/     # 采集运行、候选选择、数据查询、写作桥接
│   ├── news/          # 新闻检索、入库协调、质量、实体解析
│   ├── writing/       # 归因、编辑、写作、重写、进度协议
│   ├── review/        # 证据裁定、内容治理
│   ├── runs/          # 内容运行命令/查询门面
│   ├── tasks/         # 任务执行、协调、调度
│   ├── comparison/    # 运行对比模型、差异计算和查询
│   ├── operations/    # 运营汇总
│   └── diagnostics/   # Phase 0/1A 诊断
├── storage/
│   ├── sqlite/        # SQLite database/repositories/queries
│   ├── postgres/      # PostgreSQL 对应实现，文件名与 SQLite 对齐
│   ├── migrations/    # 公共 SQL + sqlite/postgres 方言补充
│   ├── ports.py       # 仓储协议
│   ├── database_config.py
│   ├── database_runtime.py
│   └── runtime_bundle.py  # 双数据库装配
├── web/
│   ├── routers/       # HTTP 路由
│   ├── schemas/       # 按业务分组的请求/响应模型
│   ├── services/      # Web 任务与运行适配
│   ├── events/        # 进度事件通道
│   ├── providers/     # Live 适配与预检
│   ├── dependencies.py
│   ├── errors.py
│   ├── app.py
│   └── server.py
├── domain/            # 领域模型与规则
├── ports/             # 外部能力协议
├── infrastructure/    # LLM/新闻/行情 Provider 实现
├── config/
├── reporting/
├── resources/
└── cli.py
```

## 常见修改入口

| 要修改的功能 | 入口 |
| --- | --- |
| 候选板块选择 | application/data_runs/candidate_selection_service.py |
| 数据采集运行 | application/data_runs/real_data_orchestrator.py |
| 归因与草稿生成 | application/writing/phase1b_pipeline.py |
| 审核证据裁定 | application/review/evidence_decision_service.py |
| 定时任务 | application/tasks/scheduler.py |
| 运行对比 | application/comparison/run_comparison_queries.py |
| 数据库实现选择 | storage/runtime_bundle.py |
| 审核 SQL 统计 | storage/sqlite/review_analytics.py 与 postgres 对应文件 |
| HTTP 运行 DTO | web/schemas/runs.py |
| 服务装配和路由依赖 | web/dependencies.py |

## 新代码放置规则

- 用例放对应 application 业务包；不要重新把模块堆回层的顶层。
- SQL 与数据库事务放 storage 对应方言；新增查询必须考虑双方言行为一致。
- 路由、DTO、Web 服务分开；schemas 的 __init__.py 不批量转发模型。
- domain 不依赖 application、storage 或 web。原有依赖关系本轮保留，不假装已经完成全架构解耦。
- 不因 phase 前缀移动生产链路：phase1a2_probe 属于采集链路，phase1b_pipeline 属于写作链路。
- 包 __init__.py 只描述职责，避免隐式导入导致循环依赖或副作用。
- 单元测试随业务/方言归组；跨层集成与合约测试继续按场景组织，共享 fixtures 不移动。
- migrations 路径独立于 database.py 的目录；不能因搬文件而重新编号或复制 SQL。

## 导入路径变化

```python
from sector_pulse.application.writing.phase1b_pipeline import run_phase1b_pipeline
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.web.schemas.runs import NewRunRequest
```

不提供旧路径转发。仓库外脚本若直接导入旧 Python 模块，请按
[完整迁移规则](../docs/superpowers/specs/2026-09-08-backend-package-layout-design.md)更新；
HTTP URL、CLI 命令名、环境变量和用户数据无需迁移。

## 本地验证

在项目根目录、已安装开发依赖的环境中执行：

```powershell
$env:PYTHONPATH="$PWD/backend/src"
$env:SECTOR_PULSE_DATABASE_URL=''
python -m pytest backend/tests --import-mode=importlib -m "not live and not live_llm and not postgres" -q
python -m ruff check backend/src backend/tests
python -m mypy
```

PostgreSQL 合约只能在明确隔离的测试库运行，不要将业务库连接传给测试。
前端构建后的真实 HTTP 验证用 `python scripts/verify-runtime-smoke.py`，
默认创建临时 SQLite，以 Fixture 验证生成、审核、批准、导出、审计和重试链路。
