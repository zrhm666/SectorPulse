# SectorPulse

SectorPulse 是一个证据优先的 A 股板块分析与审核工作台。项目包含 FastAPI 后端、React 运营前端、SQLite/PostgreSQL 双运行时，以及受 consent 文件保护的真实数据和 LLM 链路。

## 环境要求

- Python 3.12+
- Node.js 20+
- PostgreSQL 16（仅 PostgreSQL 模式需要）
- Docker Desktop（仅容器启动需要）

项目默认使用仓库根目录的 `.venv`，不需要额外创建 Conda 环境。

## 首次安装（Windows PowerShell）

```powershell
cd D:\work\SectorPulse
Copy-Item .env.example .env
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,postgres]"
Set-Location web
npm.cmd ci
Set-Location ..
```

编辑 `.env`，至少确认数据库模式。只有执行 Live 分析时才需要填写 LLM Base URL、API Key 和模型。

## 本地生产模式（推荐日常使用）

先构建前端，再由 FastAPI 同时提供前端和 API：

```powershell
Set-Location D:\work\SectorPulse\web
npm.cmd run build
Set-Location ..
.\.venv\Scripts\python.exe -m sector_pulse.web.server
```

浏览器访问 <http://127.0.0.1:8000>。服务会读取根目录 `.env`，并在启动时自动初始化当前数据库所需表结构。

## 前后端开发模式

终端 1（后端）：

```powershell
Set-Location D:\work\SectorPulse
.\.venv\Scripts\python.exe -m sector_pulse.web.server
```

终端 2（前端热更新）：

```powershell
Set-Location D:\work\SectorPulse\web
npm.cmd run dev
```

访问 Vite 输出的地址（通常是 <http://127.0.0.1:5173>）；`/api` 会代理到 `127.0.0.1:8000`。

## 数据库模式

### SQLite（默认）

保持 `.env` 中 `SECTOR_PULSE_DATABASE_URL` 为空：

```dotenv
SECTOR_PULSE_DATABASE_PATH=data/sector-pulse.db
SECTOR_PULSE_DATABASE_URL=
```

### PostgreSQL

先在 PostgreSQL 创建数据库和用户，再将连接串写入 `.env`：

```dotenv
SECTOR_PULSE_DATABASE_URL=postgresql+asyncpg://用户名:密码@127.0.0.1:5432/数据库名
```

设置后 PostgreSQL 优先于 SQLite；连接或迁移失败会明确终止启动，不会静默回退到 SQLite。

## Fixture 与 Live

- Fixture：内置可复现样例，不访问真实数据源，不消耗 LLM 额度，适合首次验收和回归测试。
- Live：需要完整 `.env` LLM 配置，并在仓库根目录存在 `.live-data-consent` 和 `.live-llm-consent`。

创建 consent 文件：

```powershell
New-Item .live-data-consent -ItemType File -Force
New-Item .live-llm-consent -ItemType File -Force
```

这些文件只代表本机明确授权，不会提交到 Git。运行 Live 前请先在“系统状态”页确认数据源、模型和 consent 均已就绪。

## Docker

SQLite 模式：

```powershell
Copy-Item .env.example .env
docker compose up --build sector-pulse
```

PostgreSQL 模式：

```powershell
Copy-Item .env.example .env
docker compose --profile postgres up --build sector-pulse-postgres
```

容器镜像会先构建 React 前端，再将 `web/dist` 与 Python 服务打包到同一镜像。SQLite 服务访问 <http://127.0.0.1:8010>，PostgreSQL profile 服务访问 <http://127.0.0.1:8011>。

## 验证命令

```powershell
$env:PYTHONPATH = "$PWD\backend\src"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend/src backend/tests
Set-Location web
npm.cmd test -- --run
npm.cmd run build
```

PostgreSQL 集成测试只有在 `SECTOR_PULSE_DATABASE_URL` 已进入当前进程环境时才执行；Live 测试还需要对应 consent 和显式 pytest 参数。

## 主要页面

- `/`：运营总览
- `/runs`：分析运行与新建分析
- `/review`：草稿版本、证据决定、批准、退回与导出
- `/schedules`：调度计划
- `/system`：脱敏系统状态
- `/shadow-acceptance`：已暂停的历史影子验收（只读）

项目不会自动发布内容或执行交易；批准动作只开放复制/导出能力。
