export interface DraftPatchInput {
  base_version: number
  path: string
  old_value_hash: string
  value: string
}

export interface GovernanceResponse {
  run_id?: string
  draft_id?: string
  passed?: boolean
  status?: string
  rules_version?: string
  issues: Array<{ code: string; message: string; severity: string }>
}

export async function applyDraftPatch(runId: string, draftId: string, input: DraftPatchInput) {
  const response = await fetch(`/api/runs/${runId}/drafts/${draftId}/patches`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Actor': 'reviewer' },
    body: JSON.stringify({ base_version: input.base_version, operations: [{ path: input.path, old_value_hash: input.old_value_hash, value: input.value }] }),
  })
  if (!response.ok) throw new Error(`patch failed: ${response.status}`)
  return response.json()
}

export async function fetchGovernance(runId: string): Promise<GovernanceResponse> {
  const response = await fetch(`/api/runs/${runId}/governance`)
  if (!response.ok) throw new Error(`governance failed: ${response.status}`)
  return response.json()
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

export async function fetchApproval(runId: string, draftId: string): Promise<ApprovalView | null> {
  const response = await fetch(`/api/runs/${runId}/drafts/${draftId}/approval`)
  if (!response.ok) throw new Error(`approval failed: ${response.status}`)
  return response.json()
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

export async function fetchEvidenceDecisions(runId: string, draftId: string): Promise<EvidenceDecisionView[]> {
  const response = await fetch(`/api/runs/${runId}/drafts/${draftId}/evidence-decisions`)
  if (!response.ok) throw new Error(`evidence decisions failed: ${response.status}`)
  return response.json()
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
