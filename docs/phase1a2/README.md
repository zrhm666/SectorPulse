# Phase 1A.2 真实新闻验收

Phase 1A.2 使用三个可替换的 AkShare 新闻适配器：

- `akshare-cls-news`：全局发现，作为线索来源；
- `akshare-eastmoney-news`：板块/关键词检索，保留可引用媒体元数据；
- `akshare-cninfo-disclosure`：公告检索，作为高等级事实来源。

真实网络测试默认跳过。确认已阅读数据源条款后，在仓库根目录创建空文件 `.live-data-consent`，再执行：

```powershell
$env:PYTHONPATH = "backend/src"
.\.venv\Scripts\python.exe -m pytest backend/tests/live --run-live -q
```

测试只验收状态、时间边界和可审计字段，不保存原始新闻正文，也不会自动发布内容。

Phase 1A.2 的 `ready_for_phase1b` 只有在行情未阻断、新闻质量未阻断且 cutoff 违规数为零时才允许为真。因果等级仍受限于 `MARKET_ASSOCIATION`，不会由本阶段直接生成“催化”或“明确驱动”。
