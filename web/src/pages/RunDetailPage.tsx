import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchRun, retryRun, RunSummary } from '../api'
import { useRunSSE } from '../useRuns'
import DraftTab from './tabs/DraftTab'
import EvidenceTab from './tabs/EvidenceTab'
import OverviewTab from './tabs/OverviewTab'
import RadarTab from './tabs/RadarTab'
import ReviewTab from './tabs/ReviewTab'

const TABS = ['overview', 'radar', 'draft', 'evidence', 'review'] as const
type Tab = (typeof TABS)[number]

export default function RunDetailPage() {
  const { runId } = useParams()
  const [tab, setTab] = useState<Tab>('overview')
  const [run, setRun] = useState<RunSummary | null>(null)
  const [retrying, setRetrying] = useState(false)

  const refresh = useCallback(() => {
    if (!runId) return
    fetchRun(runId).then(setRun).catch(console.error)
  }, [runId])

  // 首次进入详情页先拉取快照；SSE 只负责增量进度，避免刷新后页面空白。
  useEffect(() => {
    refresh()
  }, [refresh])

  const handleRetry = async () => {
    if (!runId) return
    setRetrying(true)
    try {
      const next = await retryRun(runId)
      window.location.href = `/runs/${next.run_id}`
    } catch (error) {
      console.error(error)
    } finally {
      setRetrying(false)
    }
  }

  const { events, done } = useRunSSE(runId ?? null, refresh)

  return (
    <div>
      <Link to="/">← 返回列表</Link>
      <h1>运行 {runId?.slice(0, 8)}</h1>
      {run && (
        <div className="card" style={{ display: 'flex', gap: 16 }}>
          <span>状态：{run.status}</span>
          <span>Provider：{run.provider}</span>
          <span>耗时：{run.elapsed_ms != null ? `${run.elapsed_ms}ms` : '—'}</span>
          <span>成本：{run.total_cost_cny != null ? `¥${run.total_cost_cny}` : '—'}</span>
          {run.status !== 'RUNNING' && (
            <button onClick={handleRetry} disabled={retrying}>
              {retrying ? '重试中...' : '重试'}
            </button>
          )}
        </div>
      )}
      <nav className="tabbar">
        {TABS.map((t) => (
          <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </nav>
      {tab === 'overview' && <OverviewTab events={events} done={done} run={run} />}
      {tab === 'radar' && <RadarTab runId={runId ?? ''} />}
      {tab === 'draft' && <DraftTab runId={runId ?? ''} />}
      {tab === 'evidence' && <EvidenceTab runId={runId ?? ''} />}
      {tab === 'review' && <ReviewTab runId={runId ?? ''} />}
    </div>
  )
}