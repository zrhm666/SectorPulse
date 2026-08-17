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

export function fetchRadar(runId: string) {
  return get<{ cards: unknown[] }>(`/runs/${runId}/radar`)
}

export function fetchDraft(runId: string) {
  return get<{ versions: unknown[] }>(`/runs/${runId}/draft`)
}

export function fetchEvidence(runId: string) {
  return get<{ sectors: unknown[]; events: unknown[]; invocations: unknown[] }>(
    `/runs/${runId}/evidence`,
  )
}

export function fetchReview(runId: string) {
  return get<{ decision: string | null; revision_round: number | null; issues: unknown[] }>(
    `/runs/${runId}/review`,
  )
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

export function draftUrl(runId: string, ext: 'md' | 'txt'): string {
  return `${BASE}/runs/${runId}/draft.${ext}`
}
