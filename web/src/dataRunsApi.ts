export interface NewDataRunRequest {
  mode: 'intraday' | 'post_close'
  provider: 'fixture' | 'live'
  lookback_hours?: number
  precandidate_limit: number
  final_candidate_limit: number
}

export interface DataRunView {
  run_id: string
  provider?: 'fixture' | 'live'
  mode: 'intraday' | 'post_close'
  status: string
  requested_at: string
  cutoff_at?: string | null
  request?: {
    mode: 'intraday' | 'post_close'
    requested_at: string
    lookback_hours: number
    precandidate_limit: number
    final_candidate_limit: number
  }
  quality: Record<string, string>
  quality_summary?: DataRunQualityView
  downgrade_reasons: string[]
  error_code?: string | null
  finished_at?: string | null
}

export interface DataRunCandidateView {
  sector_id: string
  sector_kind: string
  rank: number
  score: string
  reasons: string[]
  name?: string | null
}

export type SectorKind = 'INDUSTRY' | 'CONCEPT'
export type DataStatus = 'SUCCESS' | 'EMPTY' | 'PARTIAL' | 'STALE' | 'UNAVAILABLE' | 'FAILED'
export type DataCoverage = 'COMPLETE' | 'LINKED_ONLY'

export interface MarketSnapshotSummary {
  kind: SectorKind
  provider_id: string
  classification_version: string
  source_version: string
  observed_at: string
  collected_at: string
  sector_count: number
  available_fields?: string[]
  raw_artifact_sha256?: string | null
}

export interface MarketSectorView {
  sector_id: string
  name: string
  kind: SectorKind
  pct_change: string
  turnover_rate: string | null
  total_market_cap: string | null
  advancers: number
  decliners: number
  leader_name: string | null
  leader_pct_change: string | null
  breadth_ratio: string
  field_availability?: Record<string, boolean>
}

export interface DataRunMarketView {
  snapshots: MarketSnapshotSummary[]
  kind: SectorKind
  items: MarketSectorView[]
  total: number
  offset: number
  limit: number
}

export interface EvidenceDocumentView {
  document_id: string
  source_id: string
  citation_url: string | null
  title: string
  publisher: string | null
  summary: string | null
  published_at: string | null
  source_observed_at: string | null
  collected_at: string
  source_grade: string
}

export interface EvidenceEventView {
  event_id: string
  canonical_title: string
  first_published_at: string | null
  deduplication_reason: string
  sector_ids: string[]
  links: Array<{
    sector_id: string
    sector_kind: SectorKind
    sector_name?: string | null
    relation_type: string
    matched_entities?: string[]
    mapping_confidence: string
    mapping_reason: string
  }>
  documents: EvidenceDocumentView[]
}

export interface DataRunEvidenceView {
  events: EvidenceEventView[]
  total: number
}

export interface DataRunQualityView {
  market_quality: Record<string, string>
  news_quality: Record<string, string>
  cutoff_violation_count: number
  duplicate_document_count: number
  downgrade_reasons: string[]
  error_code?: string | null
}

export interface DataRunContentView {
  run_id: string
  status: string
  draft_id: string | null
  can_view_draft: boolean
  requested_at: string
  finished_at: string | null
}

export interface NewsSourceAcquisitionView {
  source_id: string
  status: DataStatus
  query_count: number
  status_counts: Record<DataStatus, number>
  result_count: number
  call_count: number
  retry_count: number
  duration_ms: number | null
  error_codes: string[]
}

export interface DataRunAcquisitionView {
  market_sources: MarketSnapshotSummary[]
  news_sources: NewsSourceAcquisitionView[]
  counts: {
    provider_results: number
    normalized_documents: number
    evidence_events: number
  }
  coverage: DataCoverage
  coverage_notice: string | null
}

export interface DataRunNewsRecordView extends EvidenceDocumentView {
  query_ids: string[]
  query_type: string | null
  query_status: DataStatus | null
  query_source_id: string
}

export interface DataRunNewsRecordsView {
  items: DataRunNewsRecordView[]
  total: number
  offset: number
  limit: number
  coverage: DataCoverage
  coverage_notice: string | null
}

export interface NewsRecordQuery {
  sourceId?: string
  status?: DataStatus
  offset?: number
  limit?: number
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init)
  if (!response.ok) {
    let detail: string | undefined
    try {
      const body = await response.json() as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // Preserve a useful status fallback when an upstream proxy returns non-JSON.
    }
    throw new Error(detail ?? `${path} failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

function dataRunPath(runId: string): string {
  return `/data-runs/${encodeURIComponent(runId)}`
}

export function fetchDataRun(runId: string): Promise<DataRunView> {
  return request(dataRunPath(runId))
}

export function fetchDataRuns(): Promise<DataRunView[]> {
  return request('/data-runs')
}

export function fetchDataRunCandidates(runId: string): Promise<DataRunCandidateView[]> {
  return request(`${dataRunPath(runId)}/candidates`)
}

export function fetchDataRunMarket(
  runId: string,
  kind: SectorKind,
  offset = 0,
  limit = 20,
): Promise<DataRunMarketView> {
  const query = new URLSearchParams({
    kind,
    offset: String(offset),
    limit: String(limit),
  })
  return request(`${dataRunPath(runId)}/market?${query}`)
}

export function fetchDataRunEvidence(runId: string): Promise<DataRunEvidenceView> {
  return request(`${dataRunPath(runId)}/evidence`)
}

export function fetchDataRunQuality(runId: string): Promise<DataRunQualityView> {
  return request(`${dataRunPath(runId)}/quality`)
}

export function fetchDataRunContentRun(runId: string): Promise<DataRunContentView | null> {
  return request(`${dataRunPath(runId)}/content-run`)
}

export function fetchDataRunAcquisition(runId: string): Promise<DataRunAcquisitionView> {
  return request(`${dataRunPath(runId)}/acquisition`)
}

export function fetchDataRunNewsRecords(
  runId: string,
  params: NewsRecordQuery = {},
): Promise<DataRunNewsRecordsView> {
  const query = new URLSearchParams()
  if (params.sourceId) query.set('source_id', params.sourceId)
  if (params.status) query.set('status', params.status)
  query.set('offset', String(params.offset ?? 0))
  query.set('limit', String(params.limit ?? 20))
  return request(`${dataRunPath(runId)}/news-records?${query}`)
}

export function retryDataRun(runId: string): Promise<{ run_id: string }> {
  return request(`${dataRunPath(runId)}/retry`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
  })
}

export function createDataRun(input: NewDataRunRequest): Promise<{ run_id: string }> {
  return request('/data-runs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
}

export function generateDataRunArticle(
  runId: string,
  sectorIds?: string[],
): Promise<{ run_id: string }> {
  return request(`${dataRunPath(runId)}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: sectorIds ? JSON.stringify({ sector_ids: sectorIds }) : undefined,
  })
}
