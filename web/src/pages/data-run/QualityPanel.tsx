import type { DataRunQualityView } from '../../dataRunsApi'
import StatusBadge from '../../components/ui/StatusBadge'

export default function QualityPanel({ data, loading, error }: { data: DataRunQualityView | null; loading: boolean; error: string | null }) {
  if (loading) return <p className="status-detail">正在加载质量报告…</p>
  if (error) return <p className="panel-error" role="alert">{error}</p>
  if (!data) return <p className="status-detail">质量报告尚未产生。</p>
  const sources = { ...data.market_quality, ...data.news_quality }
  return <div className="quality-report"><div className="quality-metrics"><strong>Cutoff 越界 {data.cutoff_violation_count}</strong><strong>重复文档 {data.duplicate_document_count}</strong><strong>错误码 {data.error_code ?? '无'}</strong></div><ul className="quality-list">{Object.entries(sources).map(([source, status]) => <li key={source}><strong>{source}</strong><StatusBadge status={status} /></li>)}</ul>{data.downgrade_reasons.length > 0 ? <div><h3>降级原因</h3><ul>{data.downgrade_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div> : <p className="status-detail">没有记录降级原因。</p>}</div>
}
