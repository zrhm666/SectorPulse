# Phase 4 自托管部署记录

状态：SQLite/Docker 自托管、PostgreSQL schema 初始化，以及首个业务仓储（影子验收）真实读写通过；其余业务仓储切换和插件生产化路径仍待后续演进。

- Dockerfile 和 Compose 示例已添加。
- SQLite 备份与恢复脚本已添加：`scripts/backup_sqlite.ps1`、`scripts/restore_sqlite.ps1`。
- PostgreSQL `sectorpulse` 数据库已执行 12 个 migration，`schema_migrations` 为 12 条且最大版本为 12。
- `PostgresShadowAcceptanceRepository` 已完成真实 PostgreSQL round-trip 集成测试；应用默认仍使用 SQLite，尚未切换全量业务读写。
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
