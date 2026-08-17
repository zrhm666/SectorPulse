# Phase 1C 验收说明

Phase 1C 修复覆盖 Fixture 优先的 Web 管理台、运行任务生命周期、输入快照与重试、SSE 断线恢复，以及前端组件测试和浏览器 Smoke E2E。

## 本地验证

```powershell
$env:PYTHONPATH = 'backend/src'
.\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider
cd web
npm.cmd test -- --run
npm.cmd run build
npm.cmd run test:e2e
```

Live 行情、新闻和 Live LLM 测试需要显式 consent 与网络条件；默认离线验收会跳过这些测试，不将 Fixture 结果冒充真实数据。
