import type { RunSummary } from './api'

const BASE = '/api'

export type OperationsSummary = {
  database: { backend: 'sqlite' | 'postgresql'; name: string }
  llm: { provider: string; model: string | null; budget_cny_per_run: string; configured: boolean }
  consent: { live_data: boolean; live_llm: boolean }
  providers: { live_data_available: boolean; missing_requirements: string[] }
  runs: { total: number; running: number; awaiting_review: number; failed: number; recent: RunSummary[] }
  summary: { total: number; completed_today: number; active: number; attention: number }
  trend: {
    available: boolean
    reason: string | null
    points: OperationsTrendPoint[]
  }
  readiness: {
    database: OperationsReadinessItem
    live_data: OperationsReadinessItem
    llm: OperationsReadinessItem
    scheduler: OperationsReadinessItem
  }
  recent_runs: OperationsRecentRun[]
  generated_at: string
}

export type OperationsTrendPoint = {
  date: string
  total: number
  completed: number
  failed: number
}

export type OperationsReadinessItem = {
  status: 'ready' | 'warning' | 'unavailable' | 'disabled'
  label: string
  detail: string
  detail_path: string
}

export type OperationsRecentRun = {
  run_id: string
  kind: 'content' | 'data'
  mode: string
  status: string
  provider: string
  requested_at: string
  finished_at: string | null
  elapsed_ms: number | null
  total_cost_cny: string | null
  candidate_count: number | null
  detail_path: string
}

export class OperationsApiError extends Error {
  constructor(public readonly status: number) {
    super(`运营摘要请求失败（HTTP ${status}）`)
    this.name = 'OperationsApiError'
  }
}

export async function fetchOperationsSummary(signal?: AbortSignal): Promise<OperationsSummary> {
  const response = await fetch(`${BASE}/operations/summary`, { signal })
  if (!response.ok) throw new OperationsApiError(response.status)
  return response.json() as Promise<OperationsSummary>
}
