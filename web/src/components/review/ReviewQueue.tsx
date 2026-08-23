import type { RunSummary } from '../../api'
import StatusBadge from '../ui/StatusBadge'

export default function ReviewQueue({ runs, selectedId, onSelect }: { runs: RunSummary[]; selectedId: string | null; onSelect: (id: string) => void }) {
  return <aside className="review-queue" aria-label="审核队列"><div className="review-pane__header"><h2>审核队列</h2><span>{runs.length} 篇</span></div>{runs.length === 0 ? <p className="status-detail">暂无可审核草稿。先创建一次分析，草稿完成后会出现在这里。</p> : <ul>{runs.map((run) => <li key={run.run_id}><button type="button" data-selected={selectedId === run.run_id} onClick={() => onSelect(run.run_id)}><span><strong>{run.run_id.slice(0, 8)}</strong><small>{run.provider} · {run.sector_count ?? 0} 个板块</small></span><StatusBadge status={run.status} /></button></li>)}</ul>}</aside>
}
