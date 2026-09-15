<div align="center">

# SectorPulse

**Evidence-first A-share sector analysis and review workspace.**

一个本地优先的 A 股板块研究与审核工作台：把行情、新闻、候选板块、证据归因、草稿版本和人工治理动作串成可追溯链路。

![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/Web-React-61DAFB?logo=react&logoColor=111827)
![PostgreSQL](https://img.shields.io/badge/Database-SQLite%20%7C%20PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![Local first](https://img.shields.io/badge/Deployment-Local--first-2563EB)

</div>

![SectorPulse 运营总览](docs/screenshots/sectorpulse-operations-dashboard.png)

> [!IMPORTANT]
> SectorPulse 是研究与审核工具，不构成投资建议，不自动发布内容，也不执行交易。

## 1. 项目定位与安全边界

SectorPulse 解决的是“为什么得到这个结论、用了哪些信息、谁修改或批准了它”的可追溯问题。每次运行都保留数据时间边界、来源摘要、候选版本、证据引用、Agent 任务树、预算账本、草稿版本和审核动作。

系统面向单用户、本机或受控环境部署。模型不能直接写 SQL、执行任意文件操作、改变权限、替用户选择板块或批准内容；这些动作由受控 Tool、基础服务和人工界面完成。

## 2. 当前架构：A0 调度 A1–A4

新运行只有一种执行方式：A0 研究负责人父 Agent 调度专业子 Agent，运行在仓库内置的 `vendor/aidynamic-agent` 上。旧的“工作流 / Agent”双模式已移除；请求中的 `workflow`、`agent` 或 `attribution_mode` 会被明确拒绝，而不是静默兼容。

| 角色 | 责任 | 不能做什么 |
| --- | --- | --- |
| A0 | 拆解目标、受限委派、读取状态、汇总结果、推进阶段 | 不直接写正文、不批准内容 |
| A1 | 行情与新闻采集、数据质量、候选板块提案 | 不越权研究、不确认用户选择 |
| A2 | 新闻核验、证据检查、板块归因分析 | 不写稿、不读取其他板块私有研究 |
| A3 | 大纲、草稿、有限轮次修订 | 不批准、不撤销、不扩大证据范围 |
| A4 | 独立审校、规则检查、审校意见 | 不批准、不直接改写草稿 |

确定性采集、评分、去重、领域校验、预算、租约、数据库事务和审计由 Tool 或基础服务负责。A4 的 PASS 只会把运行推进到 `WAITING_USER_REVIEW`，最终批准、退回、编辑和撤销必须由用户完成。

## 3. 受控 Skill 方法库

Skill 是维护者审核的只读方法文档，由 `aidynamic-agent` 的 `SkillManager` / `SkillTool` 按角色白名单加载。Skill 只提供研究、写作和审校方法，不包含权限、凭据、数据库身份、评分阈值或人工决定。

| 角色 | 允许加载的 Skill | 方法范围 |
| --- | --- | --- |
| A1 | `data-gap-handling`、`sector-selection` | 数据缺口处置、板块选题 |
| A2 | `causal-evidence`、`news-verification` | 因果证据核验、新闻来源核验 |
| A3 | `analysis-writing` | 分析结构、表达不确定性、受控写作 |
| A4 | `independent-review`、`news-verification` | 独立审校、来源与事实核验 |

文件位于 [`config/agent-skills`](config/agent-skills)。A0 不加载业务 Skill；它只使用父 Agent 控制工具。Agent 不能自动读取仓库外的 Codex Skill，也不能通过 Skill 获取 shell、任意 URL、SQL 或审批权限。

## 4. 一次运行的生命周期

```mermaid
flowchart LR
    A[采集行情与新闻] --> B[质量检查与候选排序]
    B --> C[用户确认板块范围]
    C --> D[A0 父 Agent]
    D --> E[A1 数据与选题]
    E --> F[A2 板块归因研究]
    F --> G[A3 编辑写作]
    G --> H[A4 独立审校]
    H --> I{PASS?}
    I -->|需修订| G
    I -->|PASS| J[WAITING_USER_REVIEW]
    J --> K[人工编辑、批准或退回]
    K --> L[复制或导出]
```

任务、尝试次数、worker 租约、预算预留、工具调用、产物引用和失败原因会持久化。父任务取消会传播到未结束子任务；只有租约过期才能恢复接管，恢复会生成新的 attempt，旧 attempt 的迟到模型、工具和产物结果不能覆盖当前状态。

Fixture 与 Live 是**依赖来源选择**，不是执行模式：

- Fixture 使用确定性样例和临时 SQLite，不联网、不消耗真实 LLM 额度。
- Live 使用配置的数据源和 OpenAI-compatible LLM，必须显式提供授权文件。

## 5. 本地快速启动

### 环境要求

- Python 3.12+
- Node.js 22.22.2+（22.x）或 24.15.0+（24.x）
- PostgreSQL 16+（可选；本机服务或容器均可）
- Windows PowerShell 示例默认从仓库根目录执行

### 安装

```powershell
git clone https://github.com/zrhm666/SectorPulse.git
Set-Location SectorPulse
Copy-Item .env.example .env

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2"
.\.venv\Scripts\python.exe -m pip install -e ".[dev,postgres]"

Set-Location web
npm.cmd ci
Set-Location ..
```

### Fixture 模式（推荐首次运行）

```powershell
Set-Location web
npm.cmd run build
Set-Location ..
.\.venv\Scripts\python.exe -m sector_pulse.web.server
```

打开 <http://127.0.0.1:9000>，新建一次 **Fixture 演练**。系统会执行真实的 A0→A4 编排，但行情、新闻、数据库和模型依赖均使用可复现的本地替身。

### Live 模式

在 `.env` 配置 OpenAI-compatible 服务，例如：

```dotenv
SECTOR_PULSE_LLM_PROVIDER=openai-compatible
SECTOR_PULSE_LLM_BASE_URL=https://your-provider.example/v1
SECTOR_PULSE_LLM_API_KEY=your-api-key
SECTOR_PULSE_LLM_MODEL=your-model
SECTOR_PULSE_LLM_TIMEOUT_SECONDS=60
SECTOR_PULSE_LLM_BUDGET_CNY=2.00
```

确认接受外部数据条款和模型费用后，再创建授权文件：

```powershell
New-Item .live-data-consent -ItemType File -Force
New-Item .live-llm-consent -ItemType File -Force
```

Live 会访问外部数据源并消耗模型额度；没有 consent 文件时不会启动对应外部调用。

## 6. 配置与目录结构

主要配置入口：

- [`config/prompts`](config/prompts)：A0–A4 系统提示词、输出契约和纠错模板
- [`config/agent-skills`](config/agent-skills)：受控 Skill 方法文档
- [`config/llm.yaml`](config/llm.yaml)：角色路由、模型、预算、超时和价格
- [`config/news_sources.yaml`](config/news_sources.yaml)：新闻来源配置
- [`config/sector_entities.yaml`](config/sector_entities.yaml)：板块与实体映射
- `.env`：本机数据库、LLM 和服务配置，禁止提交密钥

```text
SectorPulse/
├─ backend/src/sector_pulse/
│  ├─ application/          # 用例、编排、预算、任务和审核服务
│  ├─ domain/               # 行情、新闻、证据、草稿和任务模型
│  ├─ infrastructure/      # aidynamic-agent、角色、Tool、Provider 适配
│  ├─ storage/              # SQLite/PostgreSQL、迁移和 Repository
│  └─ web/                  # FastAPI、路由、Schema 和服务入口
├─ backend/tests/           # 单元、集成、PostgreSQL 和显式 Live 测试
├─ config/
│  ├─ agent-skills/         # 受控方法 Skill
│  └─ prompts/              # A0–A4 提示词与输出协议
├─ vendor/aidynamic-agent/  # 内置 Agent 框架源码
├─ web/                     # React + TypeScript 前端
├─ docs/                    # 设计、计划、验收和状态记录
└─ scripts/                 # 验证、备份和恢复脚本
```

后端模块放置规则见 [backend/README.md](backend/README.md)。

## 7. 测试与验收命令

### 后端离线回归

```powershell
$env:PYTHONPATH="$PWD/backend/src"
.\.venv\Scripts\python.exe -m pytest backend/tests -m "not live_llm and not live_data and not postgres" --import-mode=importlib -q
.\.venv\Scripts\ruff.exe check backend/src backend/tests
.\.venv\Scripts\python.exe -m mypy backend/src
```

该命令使用模拟依赖和临时 SQLite，不调用真实 LLM、实时数据源或生产数据库。

### 前端与完整门禁

```powershell
Set-Location web
npm.cmd run test:tooling
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e
npm.cmd run test:e2e:dev
Set-Location ..

powershell -ExecutionPolicy Bypass -File scripts/verify-stage0.ps1
```

首次运行 Playwright 需要先执行 `npx.cmd playwright install chromium`。

### PostgreSQL 合同测试

只允许使用专用测试库，例如 `sectorpulse_test` 或 `sector_pulse_run_comparison_test`：

```powershell
$env:SECTOR_PULSE_TEST_DATABASE_URL="postgresql+psycopg://user:password@127.0.0.1:5432/sectorpulse_test"
$env:SECTOR_PULSE_DATABASE_URL=$env:SECTOR_PULSE_TEST_DATABASE_URL
.\.venv\Scripts\python.exe -m pytest backend/tests -m postgres --import-mode=importlib -q
```

没有专用 `_test` 数据库连接时，PostgreSQL 测试应跳过，不能改用生产库。

### 真实 LLM 长链路（显式 opt-in）

真实 A0→A4 测试默认跳过。配置 `.env` 和 `.live-llm-consent` 后，明确传入项目提供的 live 参数运行；它会使用临时 SQLite 和确定性数据沙盒，但会消耗真实模型额度。

## 8. 当前完成情况与边界

已落地并持续回归的能力包括：

- 单一 A0→A4 父子 Agent 运行模型，真实复用 `vendor/aidynamic-agent`
- A1–A4 精确 Tool / Skill 白名单与作用域隔离
- 任务状态机、取消传播、worker 租约、过期接管和新 attempt
- 模型与 Tool 的共享 token、调用次数、deadline、金额预算和幂等审计
- SQLite 与 PostgreSQL Repository 合同、产物原子写入和迟到结果防覆盖
- Fixture 离线回归、专用 PostgreSQL 合同和显式真实 LLM 长链路验收
- 人工编辑、批准、退回和撤销仍由用户控制

当前边界：

- 项目仍面向单用户或受控环境，没有账号、权限和多租户体系。
- 外部数据质量和可用性受上游服务、网络和 Provider 条款影响。
- LLM 可能超时、限流或产生错误；系统记录失败，但不能替代研究判断。
- 运行列表主要面向近期已加载记录，不是无限历史检索服务。
- 系统不会自动发布文章，也不会产生交易指令。

## 9. 相关文档

- [项目当前状态](docs/PROJECT_STATUS.md)
- [产品定义](PRODUCT.md)
- [功能迁移总说明](docs/superpowers/specs/2026-09-13-feature-migration-map.md)
- [多 Agent 平台设计](docs/superpowers/specs/2026-09-12-multi-agent-platform-design.md)
- [Phase 2 实施计划与验收记录](docs/superpowers/plans/2026-09-13-multi-agent-phase2.md)
- [Phase 3a：A1 与数据 Skill](docs/superpowers/plans/2026-09-13-multi-agent-phase3a.md)
- [Phase 3b：A2 与证据 Skill](docs/superpowers/plans/2026-09-14-multi-agent-phase3b.md)
- [Phase 3c：A3/A4 与写作审校 Skill](docs/superpowers/plans/2026-09-14-multi-agent-phase3c.md)
- [后端维护指南](backend/README.md)

## License

本项目采用 [MIT License](LICENSE)。
