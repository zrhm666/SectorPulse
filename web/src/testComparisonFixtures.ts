import type { RunComparisonView, RunOption } from './runComparisonsApi'

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
