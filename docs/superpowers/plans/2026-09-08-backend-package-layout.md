# Backend Package Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans；按用户要求当前会话连续执行，不使用子代理。

**Goal:** 按业务整理 application，按方言整理 storage，按职责整理 web，保持业务行为。

**Architecture:** 保留分层；迁移清单以设计文档表格为准。全仓同步完整 Python 模块路径，不提供旧路径转发。

**Tech Stack:** Python 3.12+、FastAPI、SQLite、PostgreSQL；不新增依赖。

**Spec:** ../specs/2026-09-08-backend-package-layout-design.md

## Global Constraints

- 保持 Python 3.12+、FastAPI、现有依赖和双数据库运行方式。
- 保持 HTTP URL、请求/响应结构、CLI 命令名、配置项、日志字段与数据库表结构。
- 迁移 SQL 文件及其编号、内容和应用顺序保持不变。
- 不连接或修改业务 PostgreSQL，不创建授权文件，不调用 Live/LLM，不启动后台调度或影子测试。
- 先在隔离工作区执行，当前会话分阶段实施，不用子代理；验收后保留功能分支，合并/推送另行授权。
- 不保留旧模块的空壳转发文件；仓库内导入和 mock 字符串一次同步。Python 内部导入路径会改变，但公共命令和 HTTP 接口不变。仓库外自行编写的直接导入脚本需依迁移表更新。
- 本轮不强行拆分 domain、ports、config、reporting、resources；infrastructure 已有 llm/news/providers 分组，保留。

## 文件与接口

生产模块逐一对应设计文档 Application/Web 表和 Storage 规则；类、函数、参数不改。
新增 backend/tests/unit/test_package_layout.py，验证分包和全部模块可导入。
新增 backend/tests/unit/storage/test_packaged_migrations.py，验证默认迁移资源可应用。
新增 backend/README.md 说明职责、依赖和新增代码归属；更新根 README 目录描述。
单元测试按所属包移动；集成、合约和共享 fixtures 位置不变。

## 验证环境

使用主工作区 .venv 的 Python，PYTHONPATH 指向隔离工作区 backend/src。
清空 SECTOR_PULSE_DATABASE_URL；临时目录使用工作树 .tmp。

```powershell
$env:PYTHONPATH="$PWD/backend/src"
$env:SECTOR_PULSE_DATABASE_URL=''
& D:/work/SectorPulse/.venv/Scripts/python.exe -m pytest backend/tests --import-mode=importlib -p no:cacheprovider -m 'not live and not live_llm and not postgres' -q
```

### Task 1: Application 业务分包

接口：现有应用服务签名不变；消费者切换到 application.<业务>.<原模块>。

- [x] 建立后端全量离线基线。
- [x] 添加结构测试，先确认旧布局失败：

```python
def test_application_modules_are_grouped():
    assert {p.name for p in APPLICATION.glob("*.py")} <= {
        "__init__.py", "review_analytics.py", "postgres_review_analytics.py"
    }
```

- [x] 按设计表移动36个模块，新增9个职责明确的包；更新 backend/scripts 当前 Python 导入及 mock 字符串。
- [x] 移动对应 application 单元测试，归因 fixture 路径由 parents[2] 改为 parents[3]。
- [x] 运行结构和 application 测试，Ruff、Mypy；检查差异后提交。

### Task 2: Storage 双方言分包

接口：SQLiteDatabase、PostgresDatabase 与 RuntimeStorageBundle 原签名保持。

- [x] 添加以下默认 SQLite 迁移回归，用新导入路径运行确认失败：

```python
def test_default_migrations_apply_all_versions(tmp_path):
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    database = SQLiteDatabase(tmp_path / "database.sqlite3")
    database.initialize()
    with database.connection() as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert versions == [(n,) for n in range(1, 19)]
```

- [x] 按设计规则移动双方言 repositories、operations_query 和 application 的 SQL analytics，更新 runtime_bundle 和消费者导入。
- [x] 两个数据库 initialize 默认资源路径改为 Path(__file__).resolve().parents[1] / "migrations"，显式参数保持。
- [x] 收紧 application 顶层断言只允许 __init__.py；整理 storage 单元测试；跑真实临时 SQLite 与已有 PostgreSQL 离线测试。
- [x] 检查迁移 SQL diff 为空，Ruff、Mypy、后端回归后提交。

### Task 3: Web 职责分包

接口：app/server/dependencies/routers 不搬迁；所有 HTTP 路径和 DTO 不变。

- [x] 增加 web 顶层仅允许 __init__/app/server/dependencies/errors 的断言；旧布局应失败。
- [x] 按设计表移动 schemas/services/events/providers，更新导入（schemas.py 指向 schemas.runs，其他专属 DTO 指向各自包）。
- [x] 整理对应 web 单元测试；全仓扫描旧模块路径、动态导入及文件资源定位。
- [x] 运行 web 与 API 集成回归、Ruff、Mypy，通过后提交。

### Task 4: 验收和维护文档

- [x] 新增全模块 import 和 domain 无上层依赖约束；确认 CLI/web 入口可导入。
- [x] 全量离线后端、前端测试、tooling、构建、隔离 SQLite HTTP smoke、生产及开发 E2E。
- [x] 构建 wheel 并检查双方言迁移资源和新包；核验全部 SQL 与业务逻辑未变化。
- [x] 更新 backend/README.md 和根 README，新增验收记录：明确 PostgreSQL 实库测试未执行，不以离线检查冒充。
- [x] 更新任务勾选，最终自审并提交；保留功能分支，不合并、不推送。

## 自审

设计每项均归入上述四个任务；无业务扩展、依赖升级或业务库修改。结构测试是本轮用户明确要求的目录边界约束，行为兼容由原回归套件和资源初始化测试保障。
