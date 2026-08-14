# Phase 1A Market and News Validation

本记录对应 `84344a8` 的本地 fixture 集成验收，不代表已完成真实新闻 Provider 的网络验收。

- market provider: `fixture-market`
- news provider: `fixture-news`
- industry/concept coverage: `1 / 1`（测试阈值）
- deduplicated events: `1`
- candidates: `2`
- persisted evidence packs: `2`
- cutoff rule: all fixture observations and publication times are not later than `run_cutoff_at`
- LLM calls: none
- authorization: real RSS sources remain `RESEARCH_ONLY`

真实新闻验收需要显式配置来源 URL、网络访问和本地 consent 文件；失败必须保留 `FAILED` 语义，不能解释为“暂无新闻”。
