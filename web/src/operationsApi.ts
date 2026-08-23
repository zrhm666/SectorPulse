import type { RunSummary } from './api'

const BASE = '/api'

export type OperationsSummary = {
  database: { backend: 'sqlite' | 'postgresql'; name: string }
  llm: { provider: string; model: string | null; budget_cny_per_run: string; configured: boolean }
  consent: { live_data: boolean; live_llm: boolean }
  providers: { live_data_available: boolean; missing_requirements: string[] }
  runs: { total: number; running: number; awaiting_review: number; failed: number; recent: RunSummary[] }
}

export async function fetchOperationsSummary(): Promise<OperationsSummary> {
  const response = await fetch(`${BASE}/operations/summary`)
  if (!response.ok) throw new Error(`operations summary failed: ${response.status}`)
  return response.json() as Promise<OperationsSummary>
}
