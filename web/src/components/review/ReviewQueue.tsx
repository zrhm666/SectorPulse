import { useMemo, useState } from 'react'
import type { RunSummary } from '../../api'
import StatusBadge from '../ui/StatusBadge'

type QueueFilter = 'pending' | 'approved' | 'all'

function isApproved(run: RunSummary) {
  return run.review_decision === 'APPROVED_FOR_COPY'
}

export default function ReviewQueue({ runs, selectedId, onSelect }: { runs: RunSummary[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const [filter, setFilter] = useState<QueueFilter>('pending')
  const visibleRuns = useMemo(() => runs.filter((run) => (
    filter === 'all' || (filter === 'approved' ? isApproved(run) : !isApproved(run))
  )), [filter, runs])

  return <section className="review-queue" aria-label="审核队列">
    <div className="review-pane__header">
      <div><h2>审核队列</h2><p>{visibleRuns.length} / {runs.length} 篇</p></div>
    </div>
    <div className="review-queue__filters" role="group" aria-label="筛选审核队列">
      {([['pending', '待审核'], ['approved', '已批准'], ['all', '全部']] as const).map(([value, label]) => <button
        key={value}
        type="button"
        aria-pressed={filter === value}
        onClick={() => setFilter(value)}
      >{label}</button>)}
    </div>
    {visibleRuns.length === 0
      ? <p className="status-detail">当前筛选下没有草稿。</p>
      : <ul>{visibleRuns.map((run) => <li key={run.run_id}><button
        type="button"
        aria-label={`审核运行 ${run.run_id}`}
        data-selected={selectedId === run.run_id}
        onClick={() => onSelect(run.run_id)}
      ><span><strong>{run.run_id.slice(0, 8)}</strong><small>{run.provider} · {run.sector_count == null ? '板块数未提供' : `${run.sector_count} 个板块`}</small></span><StatusBadge status={isApproved(run) ? 'APPROVED_FOR_COPY' : run.status} /></button></li>)}</ul>}
  </section>
}
