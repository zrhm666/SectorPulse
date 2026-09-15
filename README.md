<div align="center">

# SectorPulse

**Evidence-first A-share sector research and review workspace.**

一个本地优先的 A 股板块研究工作台：从行情与新闻，到板块归因、研究写作和人工审核，保留完整、可回看的证据链。

![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/Web-React-61DAFB?logo=react&logoColor=111827)
![SQLite%20%7C%20PostgreSQL](https://img.shields.io/badge/Database-SQLite%20%7C%20PostgreSQL-4169E1?logo=postgresql&logoColor=white)

</div>

![SectorPulse 运营总览](docs/screenshots/sectorpulse-operations-dashboard.png)

> [!IMPORTANT]
> SectorPulse 是研究与审核工具，不构成投资建议，不自动发布内容，也不执行交易。

## 为什么是 SectorPulse？

SectorPulse 不只生成一篇文章。它会保存行情快照、新闻来源、候选板块、证据归因、草稿版本和人工审核动作，让你能够回看：

- 结论来自哪些数据和来源？
- 哪些证据支持或削弱了这次归因？
- 草稿经过了哪些 Agent 和人工修改？
- 当前结果是否已经通过人工审核？

## 核心能力

- **证据优先**：先采集、核验和归因，再进入写作。
- **父子 Agent 协作**：一个 A0 研究负责人调度 A1–A4 专业 Agent。
- **受控 Skill**：为选题、证据研究、写作和审校提供方法指导。
- **人工把关**：模型不能代替用户选择板块、编辑、批准或撤销。
- **可恢复运行**：任务进度、失败原因、草稿版本和运行状态可追踪。
- **本地优先**：默认 SQLite，也支持 PostgreSQL；Fixture 模式无需联网即可体验。

## 工作方式

```mermaid
flowchart TD
    A[行情与新闻] --> B[候选板块]
    B --> C[用户确认范围]
    C --> D[A0 研究负责人]
    D --> E[A1 数据与选题]
    D --> F[A2 板块归因研究]
    D --> G[A3 编辑写作]
    D --> H[A4 独立审校]
    E --> D
    F --> D
    G --> D
    H --> I{需要修订?}
    I -->|是| D
    I -->|否| J[等待人工审核]
    J --> K[编辑、批准或退回]
```

A0 负责拆解目标和委派任务；A1–A4 负责各自专业阶段。采集、评分、证据校验、预算和数据库操作由受控 Tool 或基础服务执行。

### 受控 Skill

Skill 是只读的方法库，不是权限系统。当前方法包括：

- `data-gap-handling`、`sector-selection`：数据缺口与板块选题
- `causal-evidence`、`news-verification`：因果证据与新闻核验
- `analysis-writing`：分析写作
- `independent-review`：独立审校

Skill 按角色白名单加载，不能访问任意文件、数据库或审批能力。详细方法文档位于 [`config/agent-skills`](config/agent-skills)。

## 快速开始

### 环境

- Python 3.12+
- Node.js 22+ 或 24+
- PostgreSQL 16+（可选）

### 安装

```powershell
git clone https://github.com/zrhm666/SectorPulse.git
Set-Location SectorPulse
Copy-Item .env.example .env

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,postgres]"

Set-Location web
npm.cmd ci
npm.cmd run build
Set-Location ..
```

### 启动

```powershell
.\.venv\Scripts\python.exe -m sector_pulse.web.server
```

打开 <http://127.0.0.1:9000>，创建一次 **Fixture 演练**即可开始。Fixture 使用本地样例和临时 SQLite，不访问实时数据，也不消耗真实模型额度。

## 使用真实数据和模型

在 `.env` 中配置 OpenAI-compatible LLM：

```dotenv
SECTOR_PULSE_LLM_PROVIDER=openai-compatible
SECTOR_PULSE_LLM_BASE_URL=https://your-provider.example/v1
SECTOR_PULSE_LLM_API_KEY=your-api-key
SECTOR_PULSE_LLM_MODEL=your-model
```

确认接受外部数据和模型费用后，在仓库根目录创建授权文件：

```powershell
New-Item .live-data-consent -ItemType File -Force
New-Item .live-llm-consent -ItemType File -Force
```

没有授权文件时，系统不会启动相应的外部调用。API Key 只保存在本机 `.env`，不要提交到 Git。

## 数据库

默认使用 SQLite：

```dotenv
SECTOR_PULSE_DATABASE_PATH=data/sector-pulse.db
SECTOR_PULSE_DATABASE_URL=
```

切换 PostgreSQL 时设置：

```dotenv
SECTOR_PULSE_DATABASE_URL=postgresql+psycopg://用户名:密码@127.0.0.1:5432/数据库名
```

应用不会在 PostgreSQL 连接失败时静默回退到 SQLite。

## 项目结构

```text
backend/src/sector_pulse/   后端、编排和业务 Tool
config/prompts/             A0–A4 提示词
config/agent-skills/        受控 Skill 方法库
vendor/aidynamic-agent/      内置 Agent 框架
web/                        React 前端
docs/                       设计与使用文档
```

## 进一步了解

- [产品定义](PRODUCT.md)
- [项目当前状态](docs/PROJECT_STATUS.md)
- [功能迁移说明](docs/superpowers/specs/2026-09-13-feature-migration-map.md)
- [多 Agent 架构设计](docs/superpowers/specs/2026-09-12-multi-agent-platform-design.md)
- [后端维护指南](backend/README.md)

## License

本项目采用 [MIT License](LICENSE)。
