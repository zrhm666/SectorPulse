# Phase 1B 归因与成文

## Fixture 运行

Phase 1B 默认使用 `FixtureLLMProvider`，不需要 API Key。输入文件需要包含 `Phase1BRequest` 的 `requested_at`、`contexts` 和 `gates` 字段：

```powershell
$env:PYTHONPATH = "backend/src"
.\.venv\Scripts\python.exe -m sector_pulse.cli phase1b-draft `
  --run-id 00000000-0000-0000-0000-000000000001 `
  --provider fixture `
  --input-json data/phase1b/input.json
```

可生成的草稿必须经过事实和合规审核，人工审核前不得发布；系统不提供自动发布功能，也不构成投资建议。

## 真实模型配置

真实 Provider 需要显式配置：

- `SECTOR_PULSE_LLM_API_KEY`
- `SECTOR_PULSE_LLM_BASE_URL`
- `SECTOR_PULSE_LLM_MODEL`

并在仓库根目录创建 `.live-llm-consent`。当前代码默认保持 Fixture-first，真实 Provider 接入完成后才启用 live 调用。

## 测试

```powershell
$env:PYTHONPATH = "backend/src"
.\.venv\Scripts\python.exe -m pytest backend/tests/live/test_phase1b_llm_live.py --run-live -q
```

Live 测试只检查配置、结构化 Schema、证据 ID、归因上限、Token 和成本，不断言固定文案。缺少配置时只跳过，不触网。

## 产物与成本

产物位于 `data/phase1b/<run_id>/`，包括 JSON 结果、审核报告以及通过审核后的 Markdown/纯文本草稿。默认单次模型预算为人民币 2 元，目标每天运行两次时月成本控制在 50～100 元范围内。
