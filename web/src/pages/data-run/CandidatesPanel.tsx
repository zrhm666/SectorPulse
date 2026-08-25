import type { DataRunCandidateView } from '../../dataRunsApi'

export default function CandidatesPanel({ candidates, loading, error }: { candidates: DataRunCandidateView[]; loading: boolean; error: string | null }) {
  if (loading) return <p className="status-detail">正在加载候选板块…</p>
  if (error) return <p className="panel-error" role="alert">{error}</p>
  if (candidates.length === 0) return <p className="status-detail">候选板块尚未产生，预候选排序或新闻筛选可能仍在进行。</p>
  return <ol className="candidate-list">{candidates.map((item) => <li key={item.sector_id}><span>{item.rank}</span><div><strong>{item.name ?? item.sector_id}</strong><small>{item.sector_kind} · 评分 {item.score} · {item.sector_id}</small>{item.reasons.length > 0 && <p>{item.reasons.join('；')}</p>}</div></li>)}</ol>
}
