import type { SectorKind } from './dataRunsApi'
export type { SectorKind } from './dataRunsApi'

export type ComparisonPair = { base: string; compare: string }
export type ComparisonTab = 'sectors' | 'news' | 'evidence'
export type Membership = 'BOTH' | 'ONLY_BASE' | 'ONLY_COMPARE'
export type MembershipFilter = 'ALL' | Membership
export type MissingReason = 'VALUE_MISSING' | 'FIELD_UNDECLARED' | 'SECTOR_MISSING'
export type Provider = 'fixture' | 'live'
export type RunMode = 'intraday' | 'post_close'
export interface RunOption {
  run_id: string; provider: Provider; mode: RunMode; status: string
  requested_at: string; cutoff_at: string | null; finished_at: string | null
  lookback_hours: number; precandidate_limit: number; final_candidate_limit: number; error_code: string | null
}
export interface RunOptionPage { items: RunOption[]; total: number; offset: number; limit: number }
export interface ComparisonWarning { code: string; message: string; side: 'BASE' | 'COMPARE' | 'BOTH'; kind: SectorKind | null }
export interface SnapshotContext {
  provider_id: string; classification_version: string; source_version: string
  observed_at: string; collected_at: string; available_fields: string[]
}
export interface MetricDifference {
  base: string | null; compare: string | null; delta: string | null
  unit: 'percentage_points' | 'count'; base_reason: MissingReason | null; compare_reason: MissingReason | null
}
export interface SectorComparisonRow {
  sector_id: string; kind: SectorKind; base_name: string | null; compare_name: string | null; membership: Membership
  base_rank: number | null; compare_rank: number | null; rank_delta: number | null
  base_score: string | null; compare_score: string | null; base_leader: string | null; compare_leader: string | null
  pct_change: MetricDifference; turnover_rate: MetricDifference; advancers: MetricDifference; decliners: MetricDifference
}
export interface KindComparison {
  kind: SectorKind; status: 'COMPARABLE' | 'UNAVAILABLE' | 'INCOMPATIBLE'
  base: SnapshotContext | null; compare: SnapshotContext | null; rows: SectorComparisonRow[]
}
export interface CandidateCounts { both: number; only_base: number; only_compare: number; unavailable_kinds: number }
export interface NewsCoverage { lineage: 'RECORDED' | 'UNVERIFIABLE'; recorded_count: number }
export interface NewsCounts { both: number; only_base: number; only_compare: number }
export interface RunComparisonView {
  base: RunOption; compare: RunOption; queried_at: string; warnings: ComparisonWarning[]
  candidates: CandidateCounts; kinds: KindComparison[]; base_news: NewsCoverage; compare_news: NewsCoverage; news_counts: NewsCounts | null
}
export interface CurrentNewsMetadata {
  title: string; source_id: string; publisher: string | null; summary: string | null
  citation_url: string | null; published_at: string | null; metadata_scope: 'CURRENT_STORED'
}
export interface NewsComparisonRow { document_id: string; membership: Membership; metadata: CurrentNewsMetadata | null }
export interface NewsComparisonPage {
  available: boolean; reason: 'LINEAGE_UNVERIFIABLE' | null; base_news: NewsCoverage; compare_news: NewsCoverage
  counts: NewsCounts | null; items: NewsComparisonRow[]; total: number | null; offset: number; limit: number
}
export interface EvidenceLinkView { relation_type: string; mapping_confidence: string; mapping_reason: string; rule_version: string }
export interface EvidenceComparisonRow {
  sector_id: string; event_id: string; kind: SectorKind; membership: Membership
  base: EvidenceLinkView | null; compare: EvidenceLinkView | null; current_event_title: string | null; metadata_scope: 'CURRENT_STORED'
}
export interface EvidenceComparisonPage { items: EvidenceComparisonRow[]; total: number; offset: number; limit: number; unavailable_kinds: SectorKind[] }

async function get<T>(path: string, values: Record<string, string | number | undefined>, signal: AbortSignal): Promise<T> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value !== undefined) params.set(key, String(value))
  const response = await fetch(`/api/run-comparisons${path}?${params}`, { signal })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.error?.message === 'string' ? body.error.message : '无法加载运行对比，请重试。')
  }
  return response.json() as Promise<T>
}
const ids = (pair: ComparisonPair) => ({ base_run_id: pair.base, compare_run_id: pair.compare })
export function fetchComparisonRuns(options: { provider?: Provider; mode?: RunMode; offset?: number; limit?: number }, signal: AbortSignal): Promise<RunOptionPage> {
  return get('/runs', options, signal)
}
export function fetchRunComparison(pair: ComparisonPair, signal: AbortSignal): Promise<RunComparisonView> {
  return get('', ids(pair), signal)
}
export function fetchComparisonNews(pair: ComparisonPair, options: { membership: MembershipFilter; offset: number; limit: number }, signal: AbortSignal): Promise<NewsComparisonPage> {
  return get('/news', { ...ids(pair), ...options }, signal)
}
export function fetchComparisonEvidence(pair: ComparisonPair, options: { kind?: SectorKind; sector_id?: string; offset: number; limit: number }, signal: AbortSignal): Promise<EvidenceComparisonPage> {
  return get('/evidence', { ...ids(pair), ...options }, signal)
}
