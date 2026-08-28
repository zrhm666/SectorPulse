import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchDataRun,
  fetchDataRunCandidatePage,
  fetchDataRunContentRun,
  fetchDataRunSelection,
  fetchDataRunSummary,
  type DataRunCandidatePageView,
  type DataRunContentView,
  type DataRunSelectionView,
  type DataRunView,
  type DataRunWorkflowSummaryView,
} from '../dataRunsApi'

const POLL_MS = 2_000
const MAX_RETRY_MS = 30_000
const SAFE_ERROR_MESSAGE = '工作台刷新失败，正在保留最近一次成功数据'
const ACTIVE_CONTENT_STATUSES = new Set([
  'PENDING',
  'RUNNING',
  'ATTRIBUTING',
  'EDITING',
  'WRITING',
  'REVIEWING',
])

type CoreSnapshot = {
  run: DataRunView
  summary: DataRunWorkflowSummaryView
  selection: DataRunSelectionView
  candidates: DataRunCandidatePageView
  contentRun: DataRunContentView | null
}

export type DataRunWorkbenchState = {
  run: DataRunView | null
  summary: DataRunWorkflowSummaryView | null
  selection: DataRunSelectionView | null
  candidates: DataRunCandidatePageView | null
  contentRun: DataRunContentView | null
  initialLoading: boolean
  refreshing: boolean
  stale: boolean
  error: string | null
  lastSuccessfulAt: Date | null
  refresh: () => Promise<void>
}

function isActive(snapshot: CoreSnapshot | null): boolean {
  if (!snapshot) return true
  return !snapshot.summary.terminal
    || Boolean(snapshot.contentRun && ACTIVE_CONTENT_STATUSES.has(snapshot.contentRun.status))
}

export default function useDataRunWorkbench(runId: string): DataRunWorkbenchState {
  const [snapshot, setSnapshot] = useState<CoreSnapshot | null>(null)
  const [initialLoading, setInitialLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [stale, setStale] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastSuccessfulAt, setLastSuccessfulAt] = useState<Date | null>(null)
  const snapshotRef = useRef<CoreSnapshot | null>(null)
  const mountedRef = useRef(false)
  const timerRef = useRef<number | null>(null)
  const controllerRef = useRef<AbortController | null>(null)
  const inFlightRef = useRef<Promise<void> | null>(null)
  const failureCountRef = useRef(0)
  const loadRef = useRef<() => Promise<void>>(async () => undefined)

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const schedule = useCallback((active: boolean, failed: boolean) => {
    clearTimer()
    if (!active || document.visibilityState === 'hidden' || !mountedRef.current) return
    const delay = failed
      ? Math.min(POLL_MS * (2 ** failureCountRef.current), MAX_RETRY_MS)
      : POLL_MS
    timerRef.current = window.setTimeout(() => { void loadRef.current() }, delay)
  }, [clearTimer])

  const load = useCallback((): Promise<void> => {
    if (inFlightRef.current) return inFlightRef.current
    clearTimer()
    const hadData = snapshotRef.current !== null
    if (mountedRef.current) {
      setInitialLoading(!hadData)
      setRefreshing(hadData)
    }
    const controller = new AbortController()
    controllerRef.current = controller
    let nextActive = isActive(snapshotRef.current)
    let failed = false
    const request = (async () => {
      try {
        const [run, summary, selection, candidates, contentRun] = await Promise.all([
          fetchDataRun(runId, controller.signal),
          fetchDataRunSummary(runId, controller.signal),
          fetchDataRunSelection(runId, controller.signal),
          fetchDataRunCandidatePage(runId, {}, controller.signal),
          fetchDataRunContentRun(runId, controller.signal),
        ])
        const next = { run, summary, selection, candidates, contentRun }
        nextActive = isActive(next)
        failureCountRef.current = 0
        if (!mountedRef.current || controller.signal.aborted) return
        snapshotRef.current = next
        setSnapshot(next)
        setStale(false)
        setError(null)
        setLastSuccessfulAt(new Date())
      } catch (requestError) {
        if (controller.signal.aborted || !mountedRef.current) return
        failed = true
        failureCountRef.current += 1
        setStale(snapshotRef.current !== null)
        setError(SAFE_ERROR_MESSAGE)
      } finally {
        if (controllerRef.current === controller) controllerRef.current = null
        inFlightRef.current = null
        if (mountedRef.current) {
          setInitialLoading(false)
          setRefreshing(false)
          schedule(nextActive, failed)
        }
      }
    })()
    inFlightRef.current = request
    return request
  }, [clearTimer, runId, schedule])

  loadRef.current = load

  useEffect(() => {
    mountedRef.current = true
    snapshotRef.current = null
    failureCountRef.current = 0
    setSnapshot(null)
    setInitialLoading(true)
    setStale(false)
    setError(null)
    void loadRef.current()
    const onVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        clearTimer()
      } else {
        schedule(isActive(snapshotRef.current), false)
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      mountedRef.current = false
      clearTimer()
      controllerRef.current?.abort()
      inFlightRef.current = null
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [clearTimer, runId, schedule])

  return {
    run: snapshot?.run ?? null,
    summary: snapshot?.summary ?? null,
    selection: snapshot?.selection ?? null,
    candidates: snapshot?.candidates ?? null,
    contentRun: snapshot?.contentRun ?? null,
    initialLoading,
    refreshing,
    stale,
    error,
    lastSuccessfulAt,
    refresh: load,
  }
}

export type LatestResourceState<T, P> = {
  data: T | null
  loading: boolean
  error: string | null
  load: (params: P) => Promise<void>
  reset: () => void
}

export function useLatestResource<T, P>(
  loader: (params: P, signal: AbortSignal) => Promise<T>,
  safeErrorMessage: string,
): LatestResourceState<T, P> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const controllerRef = useRef<AbortController | null>(null)
  const requestIdRef = useRef(0)

  const load = useCallback(async (params: P) => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    const requestId = requestIdRef.current + 1
    requestIdRef.current = requestId
    setLoading(true)
    try {
      const next = await loader(params, controller.signal)
      if (controller.signal.aborted || requestId !== requestIdRef.current) return
      setData(next)
      setError(null)
    } catch {
      if (controller.signal.aborted || requestId !== requestIdRef.current) return
      setError(safeErrorMessage)
    } finally {
      if (requestId === requestIdRef.current) {
        controllerRef.current = null
        setLoading(false)
      }
    }
  }, [loader, safeErrorMessage])

  const reset = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
    requestIdRef.current += 1
    setData(null)
    setLoading(false)
    setError(null)
  }, [])

  useEffect(() => () => controllerRef.current?.abort(), [])

  return { data, loading, error, load, reset }
}
