# UI refinement acceptance — 2026-09-08

## Local main integration — 2026-09-08

用户确认后，已将功能分支快进合并到本地 `main / 83570d7`。在主目录重新运行前端全量测试（230 passed）、生产构建和生产浏览器回归（61 passed），全部通过；`D:/work/SectorPulse/web/dist` 已更新。未推送远端、未重启业务服务、未操作业务数据库。

已清理本轮 `ui-refinement` 工作区和已合并分支，其他工作区保留。功能代码完整保留在 main；下文的“未合并/工作区保留”描述是合并前验收时的历史状态。现在请从主目录启动项目，浏览器使用 Ctrl+F5 刷新。

## Outcome

本轮“全站视觉与状态修正 → 运行列表、数据、审核效率优化”已实现并在隔离功能工作区验收。分支 `codex/ui-refinement`，基线 `main / 507faea`。没有修改后端代码、数据库结构、业务数据库、环境变量文件或授权文件；未调用真实 LLM/行情，不启用影子测试。

## Delivered

- 共享面板、空状态、告警间距和语义背景；辅助文字更清晰，搜索/筛选/章节控件统一 40px，窄屏 44px。
- 成本/耗时区分真实 0、未记录、运行中与不适用；采集阶段中文状态；来源与运行类型分开。已知降级码显示解释并保留原码，未知码原样展示。
- 近期运行搜索、20 条分页、正反时间排序、快捷状态、URL 条件恢复；详情返回原筛选；刷新失败保留上次记录，带就地重试。
- 数据完成后收起处理与采集详情，结果与下一步提前；警告不随详情隐藏，支持方向键及 Home/End 切换标签。
- 审核大屏专注模式不卸载编辑组件；章节定位、长正文自动增高；退回理由按需展开，取消保留文本。原自动保存、冲突恢复、历史只读和审批确认保持。

## Evidence

| Check | Result |
| --- | --- |
| `npm test -- --maxWorkers=2` | 61 files / 230 passed |
| `npm run test:tooling` | 4 passed |
| `npm run build` | TypeScript + Vite passed |
| `npm run test:e2e` | 61 passed (production bundle) |
| `npm run test:e2e:dev` | 61 passed (development) |
| Isolated non-Live pytest | 400 passed / 14 skipped / 24 deselected |
| Responsive visual check | 1440 / 1024 / 390; two bounded rounds |

浏览器通过 `web/e2e/fixtures.ts` 拦截 API；未处理的 API 请求直接让用例失败，不落入业务后端。截图使用模拟样例，不是 Live 运行效果证明。截图由 E2E 写入 `web/test-results`，未纳入版本控制，可重跑生成。

先写测试复现了零值丢失、终态指标误写待完成、原始采集状态、URL 条件不恢复、未分页、默认展开的采集过程、缺少专注/章节导航、退回理由常驻和过小原生控件，再修正。第一次完整 E2E 中两个旧用例仍要求终态显示进度，已更新为先收起、可手动展开的验收要求。

后端使用主项目 `.venv`，`PYTHONPATH` 指向本工作区，空 `SECTOR_PULSE_DATABASE_URL`，独立 `.tmp/ui-regression-<uuid>`，禁用 pytest cache。保留一条已有 Starlette/httpx 弃用警告，不作为本轮功能回归。

## Review and boundaries

按用户要求当前会话检查 diff 和交互测试，没有子代理独立审查。确认：列表读取失败不会清空已有记录；返回路径仅允许本地 `/runs`；数据选择/生成流程不重写；专注隐藏仅影响 CSS；自动保存实例不因专注切换销毁。未发现本轮新增的阻断问题。

列表查询明确只覆盖两个接口各自最近最多 50 条，不是全历史服务端搜索。PostgreSQL/Live 本轮未实测；后端兼容性依据未改代码与隔离回归，不能等同实库验收。手机筛选区仍需要滚动；移动运行对比重排、全库搜索属于后续独立增强。

由于 npm registry tarball 连接失败，新工作区依赖在核对两边 lockfile 哈希一致后从主目录离线复制；没有更改 lockfile、全局 npm 配置或主目录依赖。

## Local delivery

工作区：`D:/work/SectorPulse/.worktrees/ui-refinement`。主目录 `D:/work/SectorPulse` 的 main 和旧 dist 不会自动更新。

预览此轮页面（只启动前端；接口仍指向现有 9000 后端）：

```powershell
cd D:\work\SectorPulse\.worktrees\ui-refinement\web
npm run dev
```

生产构建已在这个 worktree 的 `web/dist` 生成，不提交 dist。未合并 main、未推送，功能工作区保留。
