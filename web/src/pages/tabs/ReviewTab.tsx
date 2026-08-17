// web/src/pages/tabs/ReviewTab.tsx
import { useEffect, useState } from 'react'
import { fetchReview } from '../../api'

interface ReviewIssue {
  issue_id: string
  severity: string
  code: string
  message: string
  suggested_fix: string | null
}

interface ReviewData {
  decision: string | null
  revision_round: number | null
  issues: ReviewIssue[]
}

export default function ReviewTab({ runId }: { runId: string }) {
  const [review, setReview] = useState<ReviewData>({ decision: null, revision_round: null, issues: [] })
  useEffect(() => {
    fetchReview(runId).then((d) => setReview(d as ReviewData)).catch(console.error)
  }, [runId])

  return (
    <div>
      <p>
        决策：<strong>{review.decision ?? '—'}</strong>，返工轮次：{review.revision_round ?? '—'}
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