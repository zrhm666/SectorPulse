export interface ShadowRunView {
  shadow_id: string
  run_id: string
  trading_date: string
  mode: string
  status: string
  created_at: string
}

export async function fetchShadowRuns(): Promise<ShadowRunView[]> {
  const response = await fetch('/api/shadow-runs')
  if (!response.ok) throw new Error(`shadow runs failed: ${response.status}`)
  return response.json()
}

export interface ShadowProgress {
  trading_days: number
  passed: number
  failed: number
  blocked: number
  remaining: number
  complete: boolean
}

export async function fetchShadowProgress(): Promise<ShadowProgress> {
  const response = await fetch('/api/shadow-runs/summary')
  if (!response.ok) throw new Error(`shadow summary failed: ${response.status}`)
  return response.json()
}
