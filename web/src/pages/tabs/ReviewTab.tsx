// web/src/pages/tabs/ReviewTab.tsx
import { useEffect, useState } from 'react'
import { fetchReview, ReviewView } from '../../api'

export default function ReviewTab({ runId }: { runId: string }) {
  const [review, setReview] = useState<ReviewView>({ decision: null, revision_round: null, issues: [] })
  useEffect(() => {
    fetchReview(runId).then(setReview).catch(console.error)
  }, [runId])

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
