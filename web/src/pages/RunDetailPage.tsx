import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchRun, retryRun, RunSummary } from '../api'
import { useRunSSE } from '../useRuns'
import DraftTab from './tabs/DraftTab'
import EvidenceTab from './tabs/EvidenceTab'
import OverviewTab from './tabs/OverviewTab'
import RadarTab from './tabs/RadarTab'
import ReviewTab from './tabs/ReviewTab'
import GovernanceTab from './tabs/GovernanceTab'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import StatusBadge from '../components/ui/StatusBadge'
import { formatDate, formatDuration } from '../runPresentation'

const TABS = [
  ['overview', '概览'], ['radar', '板块雷达'], ['evidence', '证据'], ['draft', '草稿'], ['review', '审核'], ['governance', '治理'],
] as const
type Tab = (typeof TABS)[number][0]

export default function RunDetailPage() {
  const { runId } = useParams()
  const [tab, setTab] = useState<Tab>('overview')
  const [run, setRun] = useState<RunSummary | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [retryError, setRetryError] = useState(false)

  const refresh = useCallback(() => {
    if (!runId) return
    setLoadError(false)
    fetchRun(runId).then(setRun).catch(() => setLoadError(true))
  }, [runId])

  // 首次进入详情页先拉取快照；SSE 只负责增量进度，避免刷新后页面空白。
  useEffect(() => {
    refresh()
  }, [refresh])

  const handleRetry = async () => {
    if (!runId) return
    setRetrying(true)
    setRetryError(false)
    try {
      const next = await retryRun(runId)
      window.location.href = `/runs/${next.run_id}`
    } catch (error) {
      setRetryError(true)
    } finally {
      setRetrying(false)
    }
  }

  const { events, done } = useRunSSE(runId ?? null, refresh)

  return (
    <section>
      <PageHeader title={`内容运行 ${runId?.slice(0, 8) ?? ''}`} description="查看归因、草稿、审核与治理结果。" actions={<Link className="button button-secondary" to="/runs">返回运行历史</Link>} />
      {loadError && <InlineAlert tone="error" title="无法加载运行详情"><button className="button button-secondary" type="button" onClick={refresh}>重新加载</button></InlineAlert>}
      {!run && !loadError && <LoadingState label="正在加载运行详情…" />}
      {run && <>
        <div className="detail-summary">
          <div><span>状态</span><StatusBadge status={run.status} /></div>
          <div><span>Provider</span><strong>{run.provider}</strong></div>
          <div><span>创建时间</span><strong>{formatDate(run.requested_at)}</strong></div>
          <div><span>耗时</span><strong>{formatDuration(run.elapsed_ms)}</strong></div>
          <div><span>成本</span><strong>{run.total_cost_cny != null ? `¥${run.total_cost_cny}` : '待完成'}</strong></div>
          <div><span>板块数</span><strong>{run.sector_count ?? 0}</strong></div>
        </div>
        {run.status === 'FAILED' && <InlineAlert tone="error" title="运行未完成">本次运行没有生成可审核产物。请检查系统状态；若保留了输入快照，可直接重试。</InlineAlert>}
        {retryError && <InlineAlert tone="error" title="重试未能启动">请检查 Provider 和系统配置后再试。</InlineAlert>}
        {run.retryable && <div className="detail-actions"><button className="button button-secondary" onClick={handleRetry} disabled={retrying}>{retrying ? '正在重试…' : '重新运行'}</button></div>}
        <div className="tabbar" role="tablist" aria-label="运行详情视图">{TABS.map(([key, label]) => <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}</div>
        <div role="tabpanel" className="tab-panel">
          {tab === 'overview' && <OverviewTab events={events} done={done} run={run} />}
          {tab === 'radar' && <RadarTab runId={runId ?? ''} />}
          {tab === 'draft' && <DraftTab runId={runId ?? ''} />}
          {tab === 'evidence' && <EvidenceTab runId={runId ?? ''} />}
          {tab === 'review' && <ReviewTab runId={runId ?? ''} />}
          {tab === 'governance' && <GovernanceTab runId={runId ?? ''} />}
        </div>
      </>}
    </section>
  )
}
