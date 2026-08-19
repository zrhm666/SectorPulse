# Phase 4 自托管部署记录

状态：开发中。

- Dockerfile 和 Compose 示例已添加。
- 默认使用 SQLite 数据卷。
- 健康检查使用 `/api/health`。
- 当前环境尚未执行真实 Docker 启动验收；需本机安装 Docker Desktop 后执行：

```powershell
docker compose build
docker compose up -d
Invoke-RestMethod http://127.0.0.1:8010/api/health
```

本次检查结果：Docker CLI 可用，但 Docker Desktop Linux Engine 未启动，连接
`dockerDesktopLinuxEngine` 失败。因此 Compose 构建和容器健康检查属于环境阻断，未宣称通过。

未执行 Docker 验收前，不标记 Phase 4 通过。
