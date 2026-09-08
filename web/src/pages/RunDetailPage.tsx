import { registryReturnTo } from './run-registry/registryModel'
import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
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
import SummaryStrip from '../components/ui/SummaryStrip'
import { formatDate, formatDuration, providerLabel, runCost } from '../runPresentation'
import ContentRunStageRail from '../components/runs/ContentRunStageRail'

const TABS = [
  ['overview', '概览'], ['radar', '板块雷达'], ['evidence', '证据'], ['draft', '草稿'], ['review', '审核'], ['governance', '治理'],
] as const
type Tab = (typeof TABS)[number][0]

export default function RunDetailPage() {
  const returnTo = registryReturnTo(useLocation().state)
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

  const { events, done, error: streamError } = useRunSSE(runId ?? null, refresh)

  return (
    <section className="content-run-page density-compact">
      <PageHeader title={`内容运行 ${runId?.slice(0, 8) ?? ''}`} description="查看归因、草稿、审核与治理结果。" actions={<Link className="button button-secondary" to={returnTo}>返回运行历史</Link>} />
      {loadError && <InlineAlert tone="error" title="无法加载运行详情"><button className="button button-secondary" type="button" onClick={refresh}>重新加载</button></InlineAlert>}
      {!run && !loadError && <LoadingState label="正在加载运行详情…" />}
      {run && <>
        <SummaryStrip label="内容运行摘要" items={[
          { label: '状态', value: <StatusBadge status={run.status} /> },
          { label: '数据来源', value: providerLabel(run.provider) },
          { label: '创建时间', value: formatDate(run.requested_at) },
          { label: '耗时', value: formatDuration(run.elapsed_ms, run.status) },
          { label: '成本', value: runCost(run.total_cost_cny, run.status) },
          { label: '板块数', value: run.sector_count ?? '未记录' },
        ]} />
        {run.status === 'FAILED' && <InlineAlert tone="error" title="运行未完成"><p>{run.error_message ?? '本次运行未能完成，请检查系统状态。'}</p>{run.input_json_hash && <p>已保留输入快照，可使用相同输入重新运行。</p>}</InlineAlert>}
        {run.status === 'INTERRUPTED' && <InlineAlert tone="warning" title="运行已中断">服务重启前的执行未完成，可使用已保存的输入重新运行。</InlineAlert>}
        {['UNREVIEWED', 'REVISE_REQUIRED'].includes(run.status) && <InlineAlert tone="warning" title="审核尚未通过">本次生成已结束，请检查草稿与审核结果后处理。</InlineAlert>}
        {streamError && run.status !== 'FAILED' && <InlineAlert tone="warning" title="实时进度已中断">{streamError}。页面仍保留最近一次运行快照。</InlineAlert>}
        {retryError && <InlineAlert tone="error" title="重试未能启动">请检查 Provider 和系统配置后再试。</InlineAlert>}
        <div className="detail-actions">{run.draft_id && run.status === 'READY_FOR_HUMAN_REVIEW' && <Link className="button button-primary" to={`/review?run=${encodeURIComponent(run.run_id)}`}>进入审核工作台</Link>}{run.retryable && <button className="button button-secondary" onClick={handleRetry} disabled={retrying}>{retrying ? '正在重试…' : '重新运行'}</button>}</div>
        <ContentRunStageRail events={events} done={done} run={run} />
        <div className="tabbar" role="tablist" aria-label="运行详情视图">{TABS.map(([key, label]) => <button key={key} id={`content-tab-${key}`} role="tab" aria-selected={tab === key} aria-controls={`content-panel-${key}`} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}</div>
        <div id={`content-panel-${tab}`} role="tabpanel" aria-labelledby={`content-tab-${tab}`} className="tab-panel">
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
