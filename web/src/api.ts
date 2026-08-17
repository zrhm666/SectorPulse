// web/src/api.ts
const BASE = '/api'

export interface RunSummary {
  run_id: string
  requested_at: string
  provider: string
  status: string
  elapsed_ms: number | null
  total_cost_cny: string | null
  draft_id: string | null
  input_json_hash?: string | null
  error_message?: string | null
  sector_count?: number
  review_decision?: string | null
}

/** 前端与后端证据接口共享的最小 DTO，避免页面继续依赖 unknown[]。 */
export interface NewsDocumentView {
  title: string
  citation_url: string | null
  publisher: string | null
}

export interface NewsEventView {
  event_id: string
  canonical_title: string
  documents: NewsDocumentView[]
}

export interface EvidenceView {
  sectors: Array<Record<string, unknown>>
  events: NewsEventView[]
  invocations: InvocationView[]
}

export interface InvocationView {
  stage: string
  model: string
  prompt_id: string
  prompt_version: number
  status: string
  total_tokens: number
  estimated_cost_cny: number | string
}

export interface DraftSectionView {
  section_id: string
  heading: string
  body: string
}

export interface DraftVersionView {
  version: number
  status: string
  titles: string[]
  introduction: string
  sections: DraftSectionView[]
  conclusion: string
  risk_notice: string
  sources: Array<Record<string, unknown>>
  character_count: number
}

export interface DraftView {
  versions: DraftVersionView[]
}

export interface RadarClaimView {
  claim_id: string
  text: string
}

export interface RadarCardView {
  sector_id: string
  sector_kind?: string
  attribution_level: string
  confidence: number | string
  allowed_max_level: string
  conclusion: string
  supporting_evidence_ids?: string[]
  counter_evidence: string[]
  uncertainties: string[]
  claims: RadarClaimView[]
}

export interface RadarView {
  cards: RadarCardView[]
}

export interface ReviewIssueView {
  issue_id: string
  severity: string
  code: string
  message: string
  suggested_fix: string | null
}

export interface ReviewView {
  decision: string | null
  revision_round: number | null
  issues: ReviewIssueView[]
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`)
  return res.json() as Promise<T>
}

export function fetchRuns(): Promise<RunSummary[]> {
  return get<RunSummary[]>('/runs')
}

export function fetchRun(runId: string): Promise<RunSummary> {
  return get<RunSummary>(`/runs/${runId}`)
}

export function fetchRadar(runId: string): Promise<RadarView> {
  return get<RadarView>(`/runs/${runId}/radar`)
}

export function fetchDraft(runId: string): Promise<DraftView> {
  return get<DraftView>(`/runs/${runId}/draft`)
}

export function fetchEvidence(runId: string): Promise<EvidenceView> {
  return get<EvidenceView>(`/runs/${runId}/evidence`)
}

export function fetchReview(runId: string): Promise<ReviewView> {
  return get<ReviewView>(`/runs/${runId}/review`)
}

export async function createRun(inputJson: object, provider: string): Promise<{ run_id: string }> {
  const res = await fetch(`${BASE}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input_json: inputJson, provider }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`create run failed: ${res.status} ${text}`)
  }
  return res.json() as Promise<{ run_id: string }>
}

export function fetchFixtureInput(): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/fixture-input')
}

export function draftUrl(runId: string, ext: 'md' | 'txt'): string {
  return `${BASE}/runs/${runId}/draft.${ext}`
}

export async function retryRun(runId: string): Promise<{ run_id: string }> {
  const res = await fetch(`${BASE}/runs/${runId}/retry`, { method: 'POST' })
  if (!res.ok) throw new Error(`retry run failed: ${res.status}`)
  return res.json() as Promise<{ run_id: string }>
}
