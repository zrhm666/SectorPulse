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
  pct_change?: string | null
  turnover_rate?: string | null
  total_market_cap?: string | null
  advancers?: number | null
  decliners?: number | null
  leader_name?: string | null
  leader_pct_change?: string | null
  field_availability?: Record<string, boolean>
  news_count?: number
}

export type CandidateSort = 'rank' | 'score' | 'name' | 'pct_change' | 'news_count'
export type SortDirection = 'asc' | 'desc'

export interface CandidateQuery {
  query?: string
  sort?: CandidateSort
  direction?: SortDirection
  offset?: number
  limit?: number
}

export interface DataRunCandidatePageView {
  items: DataRunCandidateView[]
  total: number
  offset: number
  limit: number
  query: string | null
  sort: CandidateSort
  direction: SortDirection
  data_version: string
}

export interface DataRunSelectionView {
  run_id: string
  confirmed: boolean
  version: number
  selected_sector_ids: string[]
  method: 'DEFAULT' | 'MANUAL' | null
  confirmed_at: string | null
  data_version: string
  edit_count: number
}

export interface DataRunWorkflowSummaryView {
  run_id: string
  status: string
  workflow_stage: string
  workflow_stage_index: number
  terminal: boolean
  requested_at: string
  cutoff_at: string | null
  finished_at: string | null
  candidate_count: number
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
  content_kind?: 'FULL_TEXT' | 'SUMMARY' | 'FLASH' | 'LINK_ONLY'
  content?: string | null
  content_available?: boolean
}

export interface DataRunNewsDetailView extends EvidenceDocumentView {
  content_kind: 'FULL_TEXT' | 'SUMMARY' | 'FLASH' | 'LINK_ONLY'
  content: string | null
  content_available: boolean
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

function signalInit(signal?: AbortSignal): RequestInit | undefined {
  return signal ? { signal } : undefined
}

function dataRunPath(runId: string): string {
  return `/data-runs/${encodeURIComponent(runId)}`
}

export function fetchDataRun(runId: string, signal?: AbortSignal): Promise<DataRunView> {
  return request(dataRunPath(runId), signalInit(signal))
}

export function fetchDataRuns(): Promise<DataRunView[]> {
  return request('/data-runs')
}

export function fetchDataRunCandidates(
  runId: string,
  signal?: AbortSignal,
): Promise<DataRunCandidateView[]> {
  return fetchDataRunCandidatePage(runId, {}, signal).then((page) => page.items)
}

export function fetchDataRunCandidatePage(
  runId: string,
  params: CandidateQuery = {},
  signal?: AbortSignal,
): Promise<DataRunCandidatePageView> {
  const query = new URLSearchParams()
  if (params.query) query.set('query', params.query)
  query.set('sort', params.sort ?? 'rank')
  query.set('direction', params.direction ?? 'asc')
  query.set('offset', String(params.offset ?? 0))
  query.set('limit', String(params.limit ?? 20))
  return request(`${dataRunPath(runId)}/candidates?${query}`, signalInit(signal))
}

export function fetchDataRunSelection(
  runId: string,
  signal?: AbortSignal,
): Promise<DataRunSelectionView> {
  return request(`${dataRunPath(runId)}/selection`, signalInit(signal))
}

export function confirmDataRunSelection(
  runId: string,
  sectorIds: string[],
  expectedVersion: number,
  signal?: AbortSignal,
): Promise<DataRunSelectionView> {
  return request(`${dataRunPath(runId)}/selection`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sector_ids: sectorIds, expected_version: expectedVersion }),
    ...(signal ? { signal } : {}),
  })
}

export function fetchDataRunSummary(
  runId: string,
  signal?: AbortSignal,
): Promise<DataRunWorkflowSummaryView> {
  return request(`${dataRunPath(runId)}/summary`, signalInit(signal))
}

export function fetchDataRunMarket(
  runId: string,
  kind: SectorKind,
  offset = 0,
  limit = 20,
  signal?: AbortSignal,
): Promise<DataRunMarketView> {
  const query = new URLSearchParams({
    kind,
    offset: String(offset),
    limit: String(limit),
  })
  return request(`${dataRunPath(runId)}/market?${query}`, signalInit(signal))
}

export function fetchDataRunEvidence(runId: string, signal?: AbortSignal): Promise<DataRunEvidenceView> {
  return request(`${dataRunPath(runId)}/evidence`, signalInit(signal))
}

export function fetchDataRunQuality(runId: string, signal?: AbortSignal): Promise<DataRunQualityView> {
  return request(`${dataRunPath(runId)}/quality`, signalInit(signal))
}

export function fetchDataRunContentRun(runId: string, signal?: AbortSignal): Promise<DataRunContentView | null> {
  return request(`${dataRunPath(runId)}/content-run`, signalInit(signal))
}

export function fetchDataRunAcquisition(runId: string, signal?: AbortSignal): Promise<DataRunAcquisitionView> {
  return request(`${dataRunPath(runId)}/acquisition`, signalInit(signal))
}

export function fetchDataRunNewsRecords(
  runId: string,
  params: NewsRecordQuery = {},
  signal?: AbortSignal,
): Promise<DataRunNewsRecordsView> {
  const query = new URLSearchParams()
  if (params.sourceId) query.set('source_id', params.sourceId)
  if (params.status) query.set('status', params.status)
  query.set('offset', String(params.offset ?? 0))
  query.set('limit', String(params.limit ?? 20))
  return request(`${dataRunPath(runId)}/news-records?${query}`, signalInit(signal))
}

export function fetchDataRunNewsRecord(
  runId: string,
  documentId: string,
  signal?: AbortSignal,
): Promise<DataRunNewsDetailView> {
  return request(
    `${dataRunPath(runId)}/news-records/${encodeURIComponent(documentId)}`,
    signalInit(signal),
  )
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
  _legacyTransientSectorIds?: string[],
): Promise<{ run_id: string }> {
  return request(`${dataRunPath(runId)}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
}
