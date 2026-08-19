import type { ReviewMetrics } from '../../editingApi'

export default function AnalyticsCard({ metrics }: { metrics: ReviewMetrics }) {
  return (
    <div className="card" aria-label="审核指标">
      <h4>审核指标</h4>
      <p>修订次数：{metrics.revision_rounds}</p>
      <p>治理阻断：{metrics.governance_failures}</p>
      <p>核准次数：{metrics.approval_count}</p>
      <p>导出次数：{metrics.export_count}</p>
      <p>模型成本：{metrics.llm_cost_cny.toFixed(2)} 元</p>
    </div>
  )
}
