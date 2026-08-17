export interface NewDataRunRequest {
  mode: 'intraday' | 'post_close'
  provider: 'fixture' | 'live'
  lookback_hours?: number
  precandidate_limit: number
  final_candidate_limit: number
}

export interface DataRunView {
  run_id: string
  mode: string
  status: string
  requested_at: string
  quality: Record<string, string>
  downgrade_reasons: string[]
}

export interface DataRunCandidateView {
  sector_id: string
  sector_kind: string
  rank: number
  score: string
  reasons: string[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init)
  if (!response.ok) throw new Error(`${path} failed: ${response.status}`)
  return response.json() as Promise<T>
}

export function fetchDataRun(runId: string): Promise<DataRunView> {
  return request(`/data-runs/${runId}`)
}

export function fetchDataRunCandidates(runId: string): Promise<DataRunCandidateView[]> {
  return request(`/data-runs/${runId}/candidates`)
}

export function createDataRun(input: NewDataRunRequest): Promise<{ run_id: string }> {
  return request('/data-runs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
}

export function generateDataRunArticle(runId: string): Promise<{ run_id: string }> {
  return request(`/data-runs/${runId}/generate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
  })
}
