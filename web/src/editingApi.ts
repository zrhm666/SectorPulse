export interface DraftPatchInput {
  base_version: number
  path: string
  old_value_hash: string
  value: string
}

export interface DraftPatchResponse {
  draft_id: string
  version: number
  status: string
  content: Record<string, unknown>
}

export class ReviewApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: 'CONFLICT' | 'INVALID' | 'NOT_FOUND' | 'UNAVAILABLE',
  ) {
    super(message)
    this.name = 'ReviewApiError'
  }
}

async function reviewRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let detail: string | null = null
    try {
      const body = await response.json() as {
        detail?: unknown
        error?: { message?: unknown }
      }
      if (typeof body.error?.message === 'string') detail = body.error.message
      else if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // Proxies can return non-JSON bodies; keep the message safe and local.
    }
    const code = response.status === 409
      ? 'CONFLICT'
      : response.status === 404
        ? 'NOT_FOUND'
        : response.status === 400 || response.status === 422
          ? 'INVALID'
          : 'UNAVAILABLE'
    throw new ReviewApiError(detail ?? '审核请求未完成，请稍后重试。', response.status, code)
  }
  return response.json() as Promise<T>
}

export interface GovernanceResponse {
  run_id?: string
  draft_id?: string
  passed?: boolean
  status?: string
  rules_version?: string
  issues: Array<{ code: string; message: string; severity: string }>
}

export async function applyDraftPatch(runId: string, draftId: string, input: DraftPatchInput, signal?: AbortSignal): Promise<DraftPatchResponse> {
  return reviewRequest<DraftPatchResponse>(`/api/runs/${runId}/drafts/${draftId}/patches`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Actor': 'reviewer' },
    body: JSON.stringify({ base_version: input.base_version, operations: [{ path: input.path, old_value_hash: input.old_value_hash, value: input.value }] }),
    ...(signal ? { signal } : {}),
  })
}

export function fetchGovernance(runId: string, signal?: AbortSignal): Promise<GovernanceResponse> {
  return reviewRequest(`/api/runs/${runId}/governance`, signal ? { signal } : undefined)
}

export interface ApprovalView {
  draft_id: string
  version: number
  status: string
  actor: string
}

export async function approveDraft(runId: string, draftId: string): Promise<ApprovalView> {
  const response = await fetch(`/api/runs/${runId}/drafts/${draftId}/approve`, {
    method: 'POST',
    headers: { 'X-Actor': 'reviewer' },
  })
  if (!response.ok) throw new Error(`approval failed: ${response.status}`)
  return response.json()
}

export async function revokeDraft(runId: string, draftId: string): Promise<ApprovalView> {
  const response = await fetch(`/api/runs/${runId}/drafts/${draftId}/revoke`, {
    method: 'POST',
    headers: { 'X-Actor': 'reviewer' },
  })
  if (!response.ok) throw new Error(`revoke failed: ${response.status}`)
  return response.json()
}

export function fetchApproval(runId: string, draftId: string, signal?: AbortSignal): Promise<ApprovalView | null> {
  return reviewRequest(`/api/runs/${runId}/drafts/${draftId}/approval`, signal ? { signal } : undefined)
}

export interface EvidenceDecisionView {
  decision_id: string
  draft_version: number
  source_id: string
  decision: 'KEEP' | 'DOWNGRADE' | 'REJECT'
  reason: string
  affected_section_ids: string[]
  created_at: string
}

export function fetchEvidenceDecisions(runId: string, draftId: string, signal?: AbortSignal): Promise<EvidenceDecisionView[]> {
  return reviewRequest(`/api/runs/${runId}/drafts/${draftId}/evidence-decisions`, signal ? { signal } : undefined)
}

export async function recordEvidenceDecision(runId: string, draftId: string, input: { source_id: string; decision: string; reason: string }): Promise<EvidenceDecisionView> {
  const response = await fetch(`/api/runs/${runId}/drafts/${draftId}/evidence-decisions`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Actor': 'local-user' }, body: JSON.stringify(input) })
  if (!response.ok) throw new Error(`evidence decision failed: ${response.status}`)
  return response.json()
}

export async function returnDraft(runId: string, draftId: string, reason: string): Promise<ApprovalView> {
  const response = await fetch(`/api/runs/${runId}/drafts/${draftId}/return`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Actor': 'local-user' }, body: JSON.stringify({ reason }) })
  if (!response.ok) throw new Error(`return draft failed: ${response.status}`)
  return response.json()
}

export function approvedExportUrl(runId: string, draftId: string): string {
  return `/api/runs/${runId}/drafts/${draftId}/export.json`
}

export interface ReviewMetrics {
  run_id: string
  review_duration_seconds: number
  patch_count: number
  revision_rounds: number
  governance_failures: number
  approval_count: number
  export_count: number
  llm_cost_cny: number
}

export async function fetchReviewMetrics(runId: string): Promise<ReviewMetrics> {
  const response = await fetch(`/api/analytics/runs/${runId}`)
  if (!response.ok) throw new Error(`analytics failed: ${response.status}`)
  return response.json()
}
