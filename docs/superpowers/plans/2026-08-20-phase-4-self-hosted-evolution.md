# Phase 4 实施计划

## 1. 配置与插件契约

- 定义 `DATABASE_URL`、插件目录和 Provider 注册接口。
- 写配置优先级、密钥不落盘和插件失败隔离测试。

## 2. 容器化启动

- 添加 Dockerfile、Compose 示例和健康检查。
- 默认 SQLite，PostgreSQL 作为显式 profile，不强制当前开发环境安装。

## 3. 部署文档与验证

- 记录启动、迁移、备份和回滚命令。
- 在当前 Windows 环境执行静态配置检查；真实 Docker 验证视本机 Docker 是否可用。

## 4. 插件演进

- 提供最小 Provider 插件协议和内置适配器注册。
- 插件异常隔离，不影响核心 Web 服务和历史数据读取。
