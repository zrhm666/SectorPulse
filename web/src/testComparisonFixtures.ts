import type { RunComparisonView, RunOption, SectorComparisonRow, SnapshotContext, NewsComparisonPage, EvidenceComparisonPage } from './runComparisonsApi'

export const runA: RunOption = {
  run_id: '00000000-0000-0000-0000-000000000001', provider: 'fixture', mode: 'post_close',
  status: 'READY_FOR_ATTRIBUTION', requested_at: '2026-09-01T07:00:00Z',
  cutoff_at: '2026-09-01T07:00:00Z', finished_at: '2026-09-01T07:01:00Z',
  lookback_hours: 24, precandidate_limit: 30, final_candidate_limit: 12, error_code: null,
}
export const runB: RunOption = { ...runA, run_id: '00000000-0000-0000-0000-000000000002', requested_at: '2026-09-02T07:00:00Z' }
export const pair = { base: runA.run_id, compare: runB.run_id }
export const comparison: RunComparisonView = {
  base: runA, compare: runB, queried_at: '2026-09-07T07:00:00Z', warnings: [],
  candidates: { both: 0, only_base: 0, only_compare: 0, unavailable_kinds: 0 }, kinds: [],
  base_news: { lineage: 'RECORDED', recorded_count: 2 }, compare_news: { lineage: 'RECORDED', recorded_count: 2 },
  news_counts: { both: 1, only_base: 1, only_compare: 1 },
}

const context: SnapshotContext = { provider_id: 'fixture-market', classification_version: 'v1', source_version: '1.0', observed_at: runA.requested_at, collected_at: runA.requested_at, available_fields: ['name', 'pct_change', 'advancers', 'decliners'] }
export const sectorRow: SectorComparisonRow = {
  sector_id: '001', kind: 'INDUSTRY', base_name: '半导体', compare_name: '半导体', membership: 'BOTH',
  base_rank: 5, compare_rank: 2, rank_delta: 3, base_score: '0.87', compare_score: '0.92', base_leader: '示例甲', compare_leader: '示例乙',
  pct_change: { base: '0', compare: '0.10', delta: '0.10', unit: 'percentage_points', base_reason: null, compare_reason: null },
  turnover_rate: { base: null, compare: '0', delta: null, unit: 'percentage_points', base_reason: 'FIELD_UNDECLARED', compare_reason: null },
  advancers: { base: '0', compare: '6', delta: '6', unit: 'count', base_reason: null, compare_reason: null },
  decliners: { base: '4', compare: '2', delta: '-2', unit: 'count', base_reason: null, compare_reason: null },
}
export const sectorComparison: RunComparisonView = { ...comparison,
  candidates: { both: 1, only_base: 0, only_compare: 1, unavailable_kinds: 0 },
  kinds: [
    { kind: 'INDUSTRY', status: 'COMPARABLE', base: context, compare: context, rows: [sectorRow] },
    { kind: 'CONCEPT', status: 'COMPARABLE', base: context, compare: context, rows: [{ ...sectorRow, kind: 'CONCEPT', base_name: '人工智能', compare_name: '人工智能', membership: 'ONLY_COMPARE', base_rank: null, compare_rank: 1, rank_delta: null, base_score: null }] },
  ],
}
export const newsComparison: NewsComparisonPage = {
  available: true, reason: null, base_news: comparison.base_news, compare_news: comparison.compare_news,
  counts: { both: 1, only_base: 1, only_compare: 1 }, total: 3, offset: 0, limit: 20,
  items: [
    { document_id: 'news-a', membership: 'ONLY_BASE', metadata: null },
    { document_id: 'news-b', membership: 'BOTH', metadata: { title: '同标题新闻', source_id: 'fixture-news', publisher: '示例来源', summary: '用于验收的留存摘要，不是真实行情新闻。', citation_url: 'https://example.test/news', published_at: runA.requested_at, metadata_scope: 'CURRENT_STORED' } },
    { document_id: 'news-c', membership: 'ONLY_COMPARE', metadata: { title: '同标题新闻', source_id: 'fixture-news', publisher: null, summary: '<script>unsafe()</script>', citation_url: 'javascript:alert(1)', published_at: null, metadata_scope: 'CURRENT_STORED' } },
  ],
}
const mapping = { relation_type: 'direct', mapping_confidence: 'high', mapping_reason: '已保存的关键词关联，不代表因果验证。', rule_version: 'v1' }
export const evidenceComparison: EvidenceComparisonPage = { total: 2, offset: 0, limit: 20, unavailable_kinds: [], items: [
  { sector_id: '001', kind: 'INDUSTRY', event_id: 'event-1', membership: 'BOTH', base: mapping, compare: { ...mapping, mapping_confidence: 'low' }, current_event_title: '示例事件', metadata_scope: 'CURRENT_STORED' },
  { sector_id: '001', kind: 'CONCEPT', event_id: 'event-1', membership: 'ONLY_BASE', base: mapping, compare: null, current_event_title: null, metadata_scope: 'CURRENT_STORED' },
] }
