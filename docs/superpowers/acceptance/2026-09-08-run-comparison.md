# 运行对比补充审查与最终本地验收

收尾日期：2026-09-08；执行覆盖 9 月 7 日至 8 日。分支：`codex/run-comparison`；实现基线：`5099334`。本报告随本轮修正提交保存，可通过文件 Git 历史定位提交。

## 结论与更正

运行对比三阶段功能在隔离工作区完成本地验收，尚未合入 main，主目录日常使用的 `web/dist` 没有更新。本结论只针对本功能与本轮回归范围，不代表全部增强路线图或真实上游服务已经验收。

对 `0f5bd42` 初版验收重新核对后，发现其完成声明过早：浏览器主要检查空态，部分设计能力未实现。已修正原报告提示、设计状态、计划勾选及项目进度，不再将初版记录作为最终证明。

## 本轮补齐

- 候选按行业/概念、入选关系筛选；展开 A/B 来源、分类版本、采集程序版本、时间及实际字段声明。
- 板块详情显示两侧名称、领涨股、换手率及涨跌家数差值；相对评分保留不可跨运行解释的提醒。未知值不追加百分号，不当作零；差值沿用后端十进制字符串。
- 新闻展示保存的发布时间、纯文本摘要和安全原文链接；缺失元数据仍保留新闻成员，展开按钮关联受控区域。
- 证据展示两侧规则版本。移动端将行情表按板块堆叠并保留 A/B 标签。
- 修正运行对比面包屑、侧栏图标文字对齐、顶栏布局及状态标签基础样式；未新建主题或修改设计 token。
- 审核队列测试改为等待异步数据加载后断言，避免将标题已出现误当成队列已经加载。

本次使用 impeccable 的实现后检查与视觉质量要求，检查桌面、平板和手机的实际构建截图，并据此修正布局；没有为截图添加无关功能。

## 验证结果

以下命令从功能工作区执行，Python 测试显式指向该工作区 `backend/src`。最终成功执行均返回 0；未通过的中间尝试见后文。

| 检查 | 命令/范围 | 结果 |
| --- | --- | --- |
| 后端普通回归 | `python -m pytest backend/tests --import-mode=importlib -p no:cacheprovider --basetemp <新建的工作区临时路径> -m 'not live and not live_llm and not postgres' -q --tb=short` | 400 passed，14 skipped，24 deselected，1 warning；68.11 秒 |
| 原生 PostgreSQL | 下列两个专项文件，使用专用测试库 | 9 passed，1 warning；14.04 秒 |
| Ruff | `python -m ruff check backend/src backend/tests` | 通过 |
| Mypy | `python -m mypy backend/src/sector_pulse` | 167 个源文件，无问题 |
| 前端单元/集成 | `npm.cmd test -- --maxWorkers=2` | 58 files，211 passed；9 月 8 日 00:12:38 开始，52.03 秒 |
| 前端工具链 | `npm.cmd run test:tooling` | 4 passed |
| 生产构建 | `npm.cmd run build` | TypeScript 与 Vite 构建通过 |
| 生产浏览器 | `npm.cmd run test:e2e` | 50 passed；21.0 秒 |
| 开发浏览器 | `npm.cmd run test:e2e:dev` | 50 passed；1.4 分钟 |

PostgreSQL 专项文件：

- `backend/tests/integration/test_postgres_comparison_run_listing.py`
- `backend/tests/integration/test_postgres_run_comparison_api.py`

环境：Python 3.12.14、Node 24.17.0、Vite 8.2.2、PostgreSQL 18.6。构建资源为 `index-DxyxkyQW.css` 和 `index-C168tcnG.js`。最终浏览器、构建和后端验证之后仅调整了前端测试等待方式及文档，未继续改产品代码。

普通后端测试的 14 个跳过不算通过，24 个排除不算通过；PostgreSQL 由专项单独验证。已有 Starlette/httpx 弃用提示仍存在。本轮没有重跑依赖漏洞审计，也没有将之前的审计结果冒充本轮结果。

## 双数据库与只读边界

SQLite 使用临时数据库，并比较查询前后的数据库内容；PostgreSQL 使用本轮隔离原生实例 `127.0.0.1:55447`、数据库 `sector_pulse_run_comparison_test`。在初始化、写入种子之前校验 `current_database()`，不读取业务 `.env`，不向本机业务数据库写测试运行。

专项覆盖终态/来源/场景过滤、历史分页、失败运行、分类不一致、缺失新闻 lineage 和元数据缺失；查询前后以内容指纹核对业务表未改变，不只比行数。专用 PostgreSQL 实例验证后已正常停止，测试目录保留于工作区忽略的 `.tmp`，没有删除业务数据。

浏览器使用受保护的 GET 拦截 Fixture；四个只读接口在后端实库 HTTP 测试中独立验证。浏览器测试不是浏览器直连业务 PostgreSQL 的 Live 全链路，不将二者混称。

## 浏览器覆盖与截图

运行对比有 10 项浏览器用例，连同原有页面在生产、开发两种模式各通过 50 项：超过 50 条历史的选择与过滤、禁止同运行比较、URL 刷新恢复、A/B 交换及前进后退、键盘标签页、分页与筛选重置、局部错误重试、旧请求晚到隔离、原文链接安全、详情展开及响应式布局。

原生 dialog 检查 Escape 与焦点返回；Shift+Tab 允许浏览器将焦点放到地址栏，但不能落到背景页面控件。仅比较测试允许主动导航造成的 GET 取消，未放松全局未知请求防护。

已检查 1440×900、1024×768、390×844：共享导航固定、内容独立滚动，无页面级横向溢出；手机结果按板块显示 A/B 标签。

- [桌面结果](../../screenshots/sectorpulse-run-comparison.png)
- [运行选择](../../screenshots/sectorpulse-run-comparison-selection.png)
- [移动端结果](../../screenshots/sectorpulse-run-comparison-mobile.png)

截图来自生产构建与浏览器 GET Fixture 响应，是界面验收示例，不是真实行情或投资结论。

## 中间失败与处理

- 系统旧 pytest 临时目录权限导致一轮 setup 失败；改用工作区全新临时路径并禁用缓存后完整回归通过，没有修改系统 ACL 或删除旧目录。
- 前端与多个全量套件并行时出现超时和审核队列过早断言；修正异步等待，最终限制两个 worker 独立复验 211 项通过。此前失去进程会话的测试未拿到结果，因此不作为证据。
- 新增用例先暴露缺失字段/布局，再修正实现；原生 dialog 的浏览器焦点行为经核实后修正测试预期，未为测试改造产品焦点行为。

## 自审与剩余限制

当前会话完成 diff、接口与类型、空值规则、只读保护及截图核对，没有使用子代理。本轮审查未发现尚未处理的阻断级问题，但不等同于对整个系统作无缺陷保证。

- 新闻文本是当前保存的元数据，不是历史正文快照；已级联删除的历史关联无法恢复。
- 既有候选主键仍为 `(run_id, sector_id)`，不含 kind；同码跨分类的持久化限制未通过本轮迁移解决。
- 本轮不采集真实行情/新闻、不调用 LLM、不恢复 20 日影子测试；真实上游可用性未验证。
- 没有新增依赖或数据库迁移；Docker 非前置条件；未修改 `.env`、consent、业务库或主目录 dist。
- 尚未合并 main、未推送远端、未验证远端 CI；这些状态不能由本地测试通过推断。
