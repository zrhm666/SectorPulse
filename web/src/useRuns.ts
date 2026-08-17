// web/src/useRuns.ts
import { useEffect, useState } from 'react'

export interface ProgressEvent {
  type: 'progress' | 'done' | 'error' | 'cancelled'
  stage?: string
  detail?: Record<string, unknown>
  status?: string
  message?: string
}

export function useRunSSE(runId: string | null, onDone?: () => void) {
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!runId) return
    let es: EventSource | null = new EventSource(`/api/runs/${runId}/events`)
    es.onmessage = (e) => {
      let event: ProgressEvent
      try {
        event = JSON.parse(e.data) as ProgressEvent
      } catch {
        return
      }
      setEvents((prev) => [...prev, event])
      if (event.type === 'done') {
        setDone(true)
        onDone?.()
        es?.close()
      } else if (event.type === 'error') {
        setError(event.message ?? '运行失败')
        setDone(true)
        es?.close()
      } else if (event.type === 'cancelled') {
        setDone(true)
        es?.close()
      }
    }
    es.onerror = () => {
      setDone(true)
      es?.close()
    }
    return () => {
      es?.close()
      es = null
    }
  }, [runId, onDone])

  return { events, done, error }
}
