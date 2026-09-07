import { useCallback, useId, useLayoutEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Button from '../../components/ui/Button'
import LoadingState from '../../components/ui/LoadingState'
import StatusBadge from '../../components/ui/StatusBadge'
import useComparisonRequest from '../../hooks/useComparisonRequest'
import { fetchComparisonRuns, type Provider, type RunMode, type RunOption } from '../../runComparisonsApi'
import { formatDate } from '../../runPresentation'
import { ComparisonPagination, QueryError } from './ComparisonShared'

export default function RunPickerDialog({ title, constraint, excludedRunId, onSelect, onClose }: {
  title: string; constraint: Pick<RunOption, 'provider' | 'mode'> | null; excludedRunId: string | null
  onSelect: (run: RunOption) => void; onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const heading = useId()
  const [provider, setProvider] = useState<Provider | ''>(constraint?.provider ?? '')
  const [mode, setMode] = useState<RunMode | ''>(constraint?.mode ?? '')
  const [offset, setOffset] = useState(0)
  const load = useCallback((signal: AbortSignal) => fetchComparisonRuns({ provider: provider || undefined, mode: mode || undefined, offset, limit: 20 }, signal), [provider, mode, offset])
  const query = useComparisonRequest(JSON.stringify([provider, mode, offset]), load)
  useLayoutEffect(() => {
    const previous = document.activeElement
    const element = dialog.current
    element?.showModal()
    return () => { element?.close(); if (previous instanceof HTMLElement && previous.isConnected) previous.focus() }
  }, [])
  return <dialog ref={dialog} className="comparison-picker" aria-labelledby={heading} onCancel={(event) => { event.preventDefault(); onClose() }}>
    <header className="comparison-picker__header"><h2 id={heading}>{title}</h2><Button variant="ghost" onClick={onClose}>关闭</Button></header>
    <p>只列出已结束的数据运行。失败运行可比较仍留存的部分数据。</p>
    <div className="comparison-filters">
      <label>数据来源<select value={provider} disabled={constraint !== null} onChange={(event) => { setProvider(event.target.value as Provider | ''); setOffset(0) }}><option value="">全部来源</option><option value="fixture">Fixture 示例</option><option value="live">Live 实时</option></select></label>
      <label>运行场景<select value={mode} disabled={constraint !== null} onChange={(event) => { setMode(event.target.value as RunMode | ''); setOffset(0) }}><option value="">全部场景</option><option value="intraday">盘中分析</option><option value="post_close">盘后复盘</option></select></label>
    </div>
    {constraint && <p className="comparison-note">已限定为另一侧相同的数据来源和场景。</p>}
    <div className="comparison-picker__results" aria-busy={query.loading}>
      {query.loading && <LoadingState label="正在读取历史运行…" />}
      {query.error && <QueryError title="历史运行读取失败" error={query.error} retry={query.reload} />}
      {query.data && <><ul className="comparison-run-options">{query.data.items.map((run) => <li key={run.run_id}>
        <button type="button" className="comparison-run-option" aria-label={`选择运行 ${run.run_id}`} disabled={run.run_id === excludedRunId} onClick={() => onSelect(run)}>
          <span><strong>{formatDate(run.requested_at)}</strong><code>{run.run_id}</code><span>{run.provider} · {run.mode === 'post_close' ? '盘后复盘' : '盘中分析'}</span></span>
          <StatusBadge status={run.status} />
        </button>
      </li>)}</ul>
      {query.data.items.length === 0 && <p>没有符合条件的运行。可以调整筛选，或<Link to="/runs">返回运行历史</Link>查看采集进度。</p>}
      <ComparisonPagination offset={offset} limit={20} total={query.data.total} busy={query.loading} onPage={setOffset} /></>}
    </div>
  </dialog>
}
