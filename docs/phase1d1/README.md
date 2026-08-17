# Phase 1D-1 验收

Phase 1D-1 提供盘中/盘后真实数据运行的状态、候选板块、质量摘要和 consent 门禁。

离线验证使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-phase1d1.ps1
```

Live 验证必须显式传入 `-RunLive`，且不会用 Fixture 结果冒充真实数据验收。
