import { useEffect, useState } from 'react'
import { fetchRun } from './api'

export interface ProgressEvent {
  type: 'progress' | 'done' | 'error' | 'cancelled'
  stage?: string
  detail?: Record<string, unknown>
  status?: string
  message?: string
}

const TERMINAL = new Set(['READY_FOR_HUMAN_REVIEW', 'FAILED', 'CANCELLED', 'BUDGET_EXCEEDED', 'ATTRIBUTION_BLOCKED', 'DRAFT_GENERATION_FAILED'])

export function useRunSSE(runId: string | null, onDone?: () => void) {
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!runId) return
    let es: EventSource | null = null
    let reconnectTimer: number | undefined
    let disposed = false

    const refreshTerminalState = async () => {
      try {
        const run = await fetchRun(runId)
        if (TERMINAL.has(run.status)) {
          setDone(true)
          onDone?.()
          return true
        }
      } catch {
        // SSE 和详情接口都暂时不可用时，保留当前进度，等待下一次重连。
      }
      return false
    }

    const connect = () => {
      if (disposed) return
      es = new EventSource(`/api/runs/${runId}/events`)
      es.onmessage = (e) => {
        let event: ProgressEvent
        try {
          event = JSON.parse(e.data) as ProgressEvent
        } catch {
          return
        }
        setEvents((prev) => [...prev, event])
        if (event.type === 'done' || event.type === 'error' || event.type === 'cancelled') {
          setDone(true)
          if (event.type === 'error') setError(event.message ?? '运行失败')
          onDone?.()
          es?.close()
        }
      }
      es.onerror = async () => {
        es?.close()
        if (await refreshTerminalState()) return
        if (!disposed) reconnectTimer = window.setTimeout(connect, 1000)
      }
    }

    void refreshTerminalState().then((terminal) => {
      if (!terminal) connect()
    })
    return () => {
      disposed = true
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer)
      es?.close()
    }
  }, [runId, onDone])

  return { events, done, error }
}