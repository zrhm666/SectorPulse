import type { GovernanceResponse } from '../../editingApi'

export default function GovernanceCard({ report }: { report: GovernanceResponse }) {
  return (
    <div className="card" aria-label="治理检查">
      <h4>{report.passed ? '治理已通过' : '治理未通过'}</h4>
      {report.issues.length === 0 ? <p>未发现问题</p> : <ul>{report.issues.map((issue) => <li key={`${issue.code}-${issue.message}`}>{issue.message}</li>)}</ul>}
    </div>
  )
}
