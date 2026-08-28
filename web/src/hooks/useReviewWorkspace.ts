import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchDraft, fetchRuns, type DraftVersionView, type RunSummary } from '../api'
import {
  fetchApproval,
  fetchEvidenceDecisions,
  fetchGovernance,
  type ApprovalView,
  type EvidenceDecisionView,
  type GovernanceResponse,
} from '../editingApi'

const WORKSPACE_ERROR = '审核材料刷新失败，当前显示最近一次成功数据。'

export type ReviewWorkspaceState = {
  runs: RunSummary[]
  selectedId: string | null
  selectedRun: RunSummary | null
  versions: DraftVersionView[]
  governance: GovernanceResponse | null
  approval: ApprovalView | null
  decisions: EvidenceDecisionView[]
  initialLoading: boolean
  workspaceLoading: boolean
  queueError: string | null
  workspaceError: string | null
  stale: boolean
  selectRun: (runId: string) => void
  refreshQueue: () => Promise<void>
  refreshWorkspace: () => Promise<void>
  refreshGovernance: () => Promise<void>
  refreshApproval: () => Promise<void>
  refreshDecisions: () => Promise<void>
}

function reviewable(items: RunSummary[]): RunSummary[] {
  return items.filter((item) => Boolean(item.draft_id) && item.status !== 'RUNNING')
}

function preferredRun(items: RunSummary[], currentId: string | null, requestedId?: string | null): string | null {
  if (currentId && items.some((item) => item.run_id === currentId)) return currentId
  if (requestedId && items.some((item) => item.run_id === requestedId)) return requestedId
  return items.find((item) => item.status === 'READY_FOR_HUMAN_REVIEW')?.run_id
    ?? items[0]?.run_id
    ?? null
}

export default function useReviewWorkspace(requestedId?: string | null): ReviewWorkspaceState {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [versions, setVersions] = useState<DraftVersionView[]>([])
  const [governance, setGovernance] = useState<GovernanceResponse | null>(null)
  const [approval, setApproval] = useState<ApprovalView | null>(null)
  const [decisions, setDecisions] = useState<EvidenceDecisionView[]>([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [workspaceLoading, setWorkspaceLoading] = useState(false)
  const [queueError, setQueueError] = useState<string | null>(null)
  const [workspaceError, setWorkspaceError] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  const mountedRef = useRef(false)
  const selectedIdRef = useRef<string | null>(null)
  const versionsRef = useRef<DraftVersionView[]>([])
  const queueControllerRef = useRef<AbortController | null>(null)
  const workspaceControllerRef = useRef<AbortController | null>(null)
  const workspaceGenerationRef = useRef(0)

  selectedIdRef.current = selectedId
  versionsRef.current = versions

  const refreshQueue = useCallback(async () => {
    queueControllerRef.current?.abort()
    const controller = new AbortController()
    queueControllerRef.current = controller
    try {
      const items = reviewable(await fetchRuns(controller.signal))
      if (!mountedRef.current || controller.signal.aborted) return
      setRuns(items)
      setSelectedId(preferredRun(items, selectedIdRef.current, requestedId))
      setQueueError(null)
    } catch {
      if (!mountedRef.current || controller.signal.aborted) return
      setQueueError('无法加载审核队列，请确认服务可用后重试。')
    } finally {
      if (queueControllerRef.current === controller) queueControllerRef.current = null
      if (mountedRef.current) setInitialLoading(false)
    }
  }, [requestedId])

  const selectedRun = useMemo(
    () => runs.find((run) => run.run_id === selectedId) ?? null,
    [runs, selectedId],
  )

  const loadWorkspace = useCallback(async (run: RunSummary, retainData: boolean) => {
    if (!run.draft_id) return
    workspaceControllerRef.current?.abort()
    const controller = new AbortController()
    workspaceControllerRef.current = controller
    const generation = workspaceGenerationRef.current + 1
    workspaceGenerationRef.current = generation
    if (!retainData) {
      setVersions([])
      setGovernance(null)
      setApproval(null)
      setDecisions([])
    }
    setWorkspaceLoading(true)
    try {
      const [draft, report, currentApproval, decisionItems] = await Promise.all([
        fetchDraft(run.run_id, controller.signal),
        fetchGovernance(run.run_id, controller.signal),
        fetchApproval(run.run_id, run.draft_id, controller.signal),
        fetchEvidenceDecisions(run.run_id, run.draft_id, controller.signal),
      ])
      if (!mountedRef.current || controller.signal.aborted
        || generation !== workspaceGenerationRef.current) return
      setVersions(draft.versions)
      setGovernance(report)
      setApproval(currentApproval)
      setDecisions(decisionItems)
      setWorkspaceError(null)
      setStale(false)
    } catch {
      if (!mountedRef.current || controller.signal.aborted
        || generation !== workspaceGenerationRef.current) return
      setWorkspaceError(WORKSPACE_ERROR)
      setStale(retainData && versionsRef.current.length > 0)
    } finally {
      if (workspaceControllerRef.current === controller) workspaceControllerRef.current = null
      if (mountedRef.current && generation === workspaceGenerationRef.current) {
        setWorkspaceLoading(false)
      }
    }
  }, [])

  const refreshWorkspace = useCallback(async () => {
    const run = runs.find((item) => item.run_id === selectedIdRef.current)
    if (run) await loadWorkspace(run, true)
  }, [loadWorkspace, runs])

  const refreshGovernance = useCallback(async () => {
    const runId = selectedIdRef.current
    if (!runId) return
    const report = await fetchGovernance(runId)
    if (mountedRef.current && selectedIdRef.current === runId) setGovernance(report)
  }, [])

  const refreshApproval = useCallback(async () => {
    const run = runs.find((item) => item.run_id === selectedIdRef.current)
    if (!run?.draft_id) return
    const currentApproval = await fetchApproval(run.run_id, run.draft_id)
    if (mountedRef.current && selectedIdRef.current === run.run_id) setApproval(currentApproval)
  }, [runs])

  const refreshDecisions = useCallback(async () => {
    const run = runs.find((item) => item.run_id === selectedIdRef.current)
    if (!run?.draft_id) return
    const items = await fetchEvidenceDecisions(run.run_id, run.draft_id)
    if (mountedRef.current && selectedIdRef.current === run.run_id) setDecisions(items)
  }, [runs])

  useEffect(() => {
    mountedRef.current = true
    void refreshQueue()
    return () => {
      mountedRef.current = false
      queueControllerRef.current?.abort()
      workspaceControllerRef.current?.abort()
    }
  }, [refreshQueue])

  useEffect(() => {
    if (selectedRun) void loadWorkspace(selectedRun, false)
  }, [loadWorkspace, selectedRun?.draft_id, selectedRun?.run_id])

  return {
    runs, selectedId, selectedRun, versions, governance, approval, decisions,
    initialLoading, workspaceLoading, queueError, workspaceError, stale,
    selectRun: setSelectedId, refreshQueue, refreshWorkspace,
    refreshGovernance, refreshApproval, refreshDecisions,
  }
}
