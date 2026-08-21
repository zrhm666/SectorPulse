# Phase 4 自托管部署记录

状态：SQLite/Docker 自托管、PostgreSQL schema 初始化、业务仓储真实读写、Web 运行时数据库选择和 Compose PostgreSQL profile 均已通过；仍需按部署环境执行最终人工长时运行观察。

- Dockerfile 和 Compose 示例已添加。
- SQLite 备份与恢复脚本已添加：`scripts/backup_sqlite.ps1`、`scripts/restore_sqlite.ps1`。
- PostgreSQL `sectorpulse` 数据库已执行 12 个 migration，`schema_migrations` 为 12 条且最大版本为 12。
- `PostgresShadowAcceptanceRepository` 已完成真实 PostgreSQL round-trip 集成测试；应用默认仍使用 SQLite，尚未切换全量业务读写。
- `PostgresRealDataRunRepository` 已完成真实 PostgreSQL round-trip 集成测试；当前仅作为可切换实现，未改变现有 SQLite 默认运行路径。
- 全量后端回归通过：184 passed、9 skipped；Ruff 全部通过。PostgreSQL 集成测试在未设置连接变量的普通回归中按预期跳过。
- 当前 PostgreSQL 仓储集成回归：14 passed；覆盖影子验收、真实数据运行、Prompt Golden、任务、Phase 1B、LLM 审计、证据、新闻、市场快照、治理、发布审计、新闻检索和草稿编辑等域。
- PostgreSQL Web smoke：设置 `SECTOR_PULSE_DATABASE_URL` 后，FastAPI lifespan 初始化成功，`/api/health`、`/api/shadow-runs/summary`、`/api/prompt-golden` 均返回 200。
- Docker PostgreSQL profile：`docker compose --profile postgres config` 通过；`sector-pulse-postgres` 镜像构建通过。
- 默认使用 SQLite 数据卷。
- 健康检查使用 `/api/health`。
- 当前环境尚未执行真实 Docker 启动验收；需本机安装 Docker Desktop 后执行：

```powershell
docker compose build
docker compose up -d
Invoke-RestMethod http://127.0.0.1:8010/api/health
```

本次检查结果：Docker Compose 构建成功，容器状态为 `healthy`，`/api/health` 返回 `ok`。

未执行 Docker 验收前，不标记 Phase 4 通过。
