// web/src/pages/tabs/ReviewTab.tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchReview, ReviewView } from '../../api'
import InlineAlert from '../../components/ui/InlineAlert'
import LoadingState from '../../components/ui/LoadingState'

export default function ReviewTab({ runId }: { runId: string }) {
  const [review, setReview] = useState<ReviewView>({ decision: null, revision_round: null, issues: [] })
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const requestId = useRef(0)
  const load = useCallback(async () => {
    const currentRequest = ++requestId.current
    setLoading(true)
    setLoadError(false)
    try {
      const result = await fetchReview(runId)
      if (currentRequest === requestId.current) setReview(result)
    } catch {
      if (currentRequest === requestId.current) setLoadError(true)
    } finally {
      if (currentRequest === requestId.current) setLoading(false)
    }
  }, [runId])
  useEffect(() => {
    void load()
    return () => { requestId.current += 1 }
  }, [load])

  if (loading) return <LoadingState label="正在加载审核结果…" />
  if (loadError) return <InlineAlert tone="error" title="无法加载审核结果"><button className="button button-secondary" type="button" onClick={() => void load()}>重新加载</button></InlineAlert>

  return (
    <div>
      <p>
        决策：<strong>{review.decision ?? '暂无'}</strong>，返工轮次：{review.revision_round ?? '暂无'}
      </p>
      {review.issues.length === 0 && <p>无审核问题。</p>}
      {review.issues.map((issue) => (
        <div key={issue.issue_id} className="card">
          <p>
            [{issue.severity}] {issue.code}：{issue.message}
          </p>
          {issue.suggested_fix && <p>建议：{issue.suggested_fix}</p>}
        </div>
      ))}
    </div>
  )
}
