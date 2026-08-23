const BASE = '/api'

export interface ScheduleView {
  schedule_id: string
  name: string
  mode: string
  timezone: string
  local_time: string
  trading_days: string
  enabled: boolean
  next_run_at: string | null
}

export type NewScheduleInput = {
  name: string
  mode: string
  timezone: string
  local_time: string
  trading_days: string
  enabled: boolean
  input_template: Record<string, unknown>
}

export interface TaskRunView {
  run_id: string
  status: string
  provider: string
  input_fingerprint: string
  stages: Array<{ stage: string; attempt_no: number; status: string; error_code: string | null }>
  events: Array<{ event_type: string; summary: string; created_at: string }>
  downgrade_reasons: string[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init)
  if (!response.ok) throw new Error(`${path} failed: ${response.status}`)
  return response.json() as Promise<T>
}

export function fetchSchedules(): Promise<ScheduleView[]> {
  return request<ScheduleView[]>('/schedules')
}

export function createSchedule(input: NewScheduleInput): Promise<ScheduleView> {
  return request<ScheduleView>('/schedules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export function triggerSchedule(scheduleId: string): Promise<{ run_id: string }> {
  return request<{ run_id: string }>(`/schedules/${scheduleId}/trigger`, { method: 'POST' })
}

export function fetchTaskRun(runId: string): Promise<TaskRunView> {
  return request<TaskRunView>(`/task-runs/${runId}`)
}
