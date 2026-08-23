# Phase 3 分析运行工作台验收报告

日期：2026-08-23
结论：通过

## 完成范围

- 新增 `/runs/new` 三阶段新建分析页面，移除内部 JSON 文本框和旧模态框。
- Fixture 演练与 Live 实时运行共用同一入口；Live 根据 operations summary 在提交前阻断缺失配置或授权。
- 运行历史合并内容运行和数据运行，提供状态、模式、Provider、日期、耗时、成本和详情入口。
- 内容运行详情包含摘要、阶段轨迹、概览、板块雷达、证据、草稿、审核、治理和受控重试。
- 数据运行详情包含摘要、处理轨迹、质量状态、降级原因、候选板块和分析稿生成入口。
- 后端内容运行详情增加 `retryable`；真实数据运行查询改为稳定的前端扁平合同。

## 自动化证据

- 前端：`npm.cmd test -- --run`，21 个测试文件、41 项测试通过。
- 构建：`npm.cmd run build`，TypeScript 与 Vite 生产构建通过。
- 后端：`python -m pytest backend/tests -q`，189 项通过、21 项按环境条件跳过、0 项失败。
- Impeccable detector：Phase 3 四个主要页面无检测项。
- taste-skill 终检：无可见长破折号、无旧 JSON 入口、状态/空/加载/错误均有明确表现。

## 浏览器证据

通过应用内浏览器对本地生产构建执行真实 Fixture 流程：

1. 打开 `/runs/new`，选择盘后复盘。
2. Live 方式正确显示 `.live-data-consent`、数据源和 `.live-llm-consent` 缺失项，并禁用下一步。
3. 切回 Fixture，提交后创建运行 `58e3937c-ca62-4a2e-b10e-d100d55f87ee`。
4. 成功导航到内容运行详情；状态为待人工审核，Provider 为 fixture，板块数为 8，成本为 ¥0。
5. 治理标签返回“治理已通过”，未发现治理问题。
6. 1280px 和 390px 均无横向溢出；390px 显示移动菜单，运行历史表格转为字段列表。

该流程没有访问实时行情，也没有调用真实 LLM。

## 已知边界

- PostgreSQL 专用集成测试在未向测试进程提供 `SECTOR_PULSE_DATABASE_URL` 时按预期跳过；现有运行时数据库连接由系统状态页单独展示。
- Live 流程本次仅验证预检阻断，没有消耗真实 Provider 或 LLM 额度。
- Phase 3 影子验收继续保持暂停。
