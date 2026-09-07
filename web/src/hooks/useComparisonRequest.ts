import { useCallback, useEffect, useState } from 'react'

/** Keyed read-only request: cancelled requests cannot publish data, errors or completion. */
export default function useComparisonRequest<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>) {
  const [revision, setRevision] = useState(0)
  const requestKey = key === null ? null : `${key}:${revision}`
  const [state, setState] = useState<{ key: string | null; data: T | null; error: string | null; loading: boolean }>({ key: null, data: null, error: null, loading: false })
  useEffect(() => {
    if (requestKey === null) return
    const controller = new AbortController()
    let active = true
    setState({ key: requestKey, data: null, error: null, loading: true })
    void load(controller.signal).then((data) => {
      if (active && !controller.signal.aborted) setState({ key: requestKey, data, error: null, loading: false })
    }).catch((reason: unknown) => {
      if (active && !controller.signal.aborted) setState({ key: requestKey, data: null, error: reason instanceof Error ? reason.message : '读取失败，请重试。', loading: false })
    })
    return () => { active = false; controller.abort() }
  }, [requestKey, load])
  const reload = useCallback(() => setRevision((value) => value + 1), [])
  // Mask stale state during render, before the replacement effect can run.
  const current = requestKey !== null && state.key === requestKey
  return { data: current ? state.data : null, error: current ? state.error : null, loading: requestKey !== null && (!current || state.loading), reload }
}
