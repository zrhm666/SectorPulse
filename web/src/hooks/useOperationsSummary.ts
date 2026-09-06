import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchOperationsSummary, type OperationsSummary } from '../operationsApi'

const ACTIVE_POLL_MS = 5_000
const SAFE_ERROR_MESSAGE = '运营数据刷新失败，请稍后重试'

export type OperationsSummaryState = {
  data: OperationsSummary | null
  initialLoading: boolean
  refreshing: boolean
  stale: boolean
  error: string | null
  lastSuccessfulAt: Date | null
  refresh: () => Promise<void>
}

export default function useOperationsSummary(): OperationsSummaryState {
  const [data, setData] = useState<OperationsSummary | null>(null)
  const [initialLoading, setInitialLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [stale, setStale] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastSuccessfulAt, setLastSuccessfulAt] = useState<Date | null>(null)
  const dataRef = useRef<OperationsSummary | null>(null)
  const mountedRef = useRef(false)
  const timerRef = useRef<number | null>(null)
  const controllerRef = useRef<AbortController | null>(null)
  const inFlightRef = useRef<Promise<void> | null>(null)
  const loadRef = useRef<() => Promise<void>>(async () => undefined)

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const schedule = useCallback((active: number) => {
    clearTimer()
    if (active <= 0 || document.visibilityState === 'hidden' || !mountedRef.current) return
    timerRef.current = window.setTimeout(() => { void loadRef.current() }, ACTIVE_POLL_MS)
  }, [clearTimer])

  const load = useCallback((): Promise<void> => {
    if (inFlightRef.current) return inFlightRef.current
    clearTimer()
    const hadData = dataRef.current !== null
    if (mountedRef.current) {
      setInitialLoading(!hadData)
      setRefreshing(hadData)
    }
    const controller = new AbortController()
    controllerRef.current = controller
    let nextActive = dataRef.current?.summary.active ?? 0
    const request = (async () => {
      try {
        const next = await fetchOperationsSummary(controller.signal)
        if (!mountedRef.current || controller.signal.aborted || controllerRef.current !== controller) return
        nextActive = next.summary.active
        dataRef.current = next
        setData(next)
        setStale(false)
        setError(null)
        setLastSuccessfulAt(new Date())
      } catch (requestError) {
        if (controller.signal.aborted || !mountedRef.current || controllerRef.current !== controller) return
        setError(SAFE_ERROR_MESSAGE)
        setStale(dataRef.current !== null)
      } finally {
        // A cancelled mount must not finish or reschedule its replacement.
        if (controllerRef.current === controller) {
          controllerRef.current = null
          inFlightRef.current = null
          if (mountedRef.current) {
            setInitialLoading(false)
            setRefreshing(false)
            schedule(nextActive)
          }
        }
      }
    })()
    inFlightRef.current = request
    return request
  }, [clearTimer, schedule])

  loadRef.current = load

  useEffect(() => {
    mountedRef.current = true
    void loadRef.current()
    const onVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        clearTimer()
      } else {
        schedule(dataRef.current?.summary.active ?? 0)
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      mountedRef.current = false
      clearTimer()
      controllerRef.current?.abort()
      controllerRef.current = null
      inFlightRef.current = null
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [clearTimer, schedule])

  return {
    data,
    initialLoading,
    refreshing,
    stale,
    error,
    lastSuccessfulAt,
    refresh: load,
  }
}
