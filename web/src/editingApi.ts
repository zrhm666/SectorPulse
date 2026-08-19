export interface DraftPatchInput {
  base_version: number
  path: string
  old_value_hash: string
  new_value: string
}

export interface GovernanceResponse {
  run_id: string
  draft_id: string
  passed: boolean
  issues: Array<{ code: string; message: string; severity: string }>
}

export async function applyDraftPatch(runId: string, draftId: string, input: DraftPatchInput) {
  const response = await fetch(`/api/runs/${runId}/drafts/${draftId}/patches`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Actor': 'reviewer' },
    body: JSON.stringify(input),
  })
  if (!response.ok) throw new Error(`patch failed: ${response.status}`)
  return response.json()
}

export async function fetchGovernance(runId: string): Promise<GovernanceResponse> {
  const response = await fetch(`/api/runs/${runId}/governance`)
  if (!response.ok) throw new Error(`governance failed: ${response.status}`)
  return response.json()
}
