import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import {
  type DataRunCandidateView,
  type DataRunContentView,
  type DataRunEvidenceView,
  type DataRunMarketView,
  type DataRunQualityView,
  type DataRunView,
  type SectorKind,
  fetchDataRun,
  fetchDataRunCandidates,
  fetchDataRunContentRun,
  fetchDataRunEvidence,
  fetchDataRunMarket,
  fetchDataRunQuality,
  generateDataRunArticle,
  retryDataRun,
} from '../dataRunsApi'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import StatusBadge from '../components/ui/StatusBadge'
import { formatDate } from '../runPresentation'
import CandidatesPanel from './data-run/CandidatesPanel'
import DataRunActionPanel from './data-run/DataRunActionPanel'
import DataRunTimeline from './data-run/DataRunTimeline'
import EvidencePanel from './data-run/EvidencePanel'
import MarketPanel from './data-run/MarketPanel'
import QualityPanel from './data-run/QualityPanel'

const TERMINAL_STATUSES = new Set([
  'READY_FOR_ATTRIBUTION', 'DEGRADED', 'BLOCKED', 'FAILED',
  'CANCELLED', 'INTERRUPTED',
])
type WorkbenchTab = 'market' | 'candidates' | 'evidence' | 'quality'

function message(reason: unknown, fallback: string): string {
  return reason instanceof Error && reason.message ? reason.message : fallback
}

export default function DataRunPage() {
  const { runId = '' } = useParams()
  const navigate = useNavigate()
  const [run, setRun] = useState<DataRunView | null>(null)
  const [loading, setLoading] = useState(true)
  const [runError, setRunError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<WorkbenchTab>('market')
  const [candidates, setCandidates] = useState<DataRunCandidateView[]>([])
  const [candidatesLoading, setCandidatesLoading] = useState(true)
  const [candidatesError, setCandidatesError] = useState<string | null>(null)
  const [contentRun, setContentRun] = useState<DataRunContentView | null>(null)
  const [marketKind, setMarketKind] = useState<SectorKind>('INDUSTRY')
  const [marketOffset, setMarketOffset] = useState(0)
  const [market, setMarket] = useState<DataRunMarketView | null>(null)
  const [marketLoading, setMarketLoading] = useState(true)
  const [marketError, setMarketError] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<DataRunEvidenceView | null>(null)
  const [evidenceLoading, setEvidenceLoading] = useState(false)
  const [evidenceError, setEvidenceError] = useState<string | null>(null)
  const [quality, setQuality] = useState<DataRunQualityView | null>(null)
  const [qualityLoading, setQualityLoading] = useState(false)
  const [qualityError, setQualityError] = useState<string | null>(null)
  const [actionBusy, setActionBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const loadRun = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true)
    try {
      setRun(await fetchDataRun(runId))
      setRunError(null)
    } catch (reason) {
      setRunError(message(reason, '无法加载数据运行，请确认服务可用后重试。'))
    } finally {
      if (showLoading) setLoading(false)
    }
  }, [runId])

  const loadCandidates = useCallback(async () => {
    setCandidatesLoading(true)
    try {
      setCandidates(await fetchDataRunCandidates(runId))
      setCandidatesError(null)
    } catch (reason) {
      setCandidatesError(message(reason, '候选板块加载失败。'))
    } finally {
      setCandidatesLoading(false)
    }
  }, [runId])

  useEffect(() => {
    setRun(null)
    setContentRun(null)
    setEvidence(null)
    setQuality(null)
    setMarket(null)
    setActionError(null)
    void loadRun()
    void loadCandidates()
    fetchDataRunContentRun(runId).then(setContentRun).catch(() => setContentRun(null))
  }, [loadCandidates, loadRun, runId])

  useEffect(() => {
    if (!run || TERMINAL_STATUSES.has(run.status)) return
    const timer = window.setInterval(() => { void loadRun(false) }, 2000)
    return () => window.clearInterval(timer)
  }, [loadRun, run])

  useEffect(() => {
    if (activeTab !== 'market') return
    let cancelled = false
    setMarketLoading(true)
    fetchDataRunMarket(runId, marketKind, marketOffset, 20)
      .then((value) => { if (!cancelled) { setMarket(value); setMarketError(null) } })
      .catch((reason) => { if (!cancelled) setMarketError(message(reason, '行情板块加载失败。')) })
      .finally(() => { if (!cancelled) setMarketLoading(false) })
    return () => { cancelled = true }
  }, [activeTab, marketKind, marketOffset, runId])

  useEffect(() => {
    if (activeTab !== 'evidence' || evidence) return
    let cancelled = false
    setEvidenceLoading(true)
    fetchDataRunEvidence(runId)
      .then((value) => {
        if (!cancelled) { setEvidence(value); setEvidenceError(null); setEvidenceLoading(false) }
      })
      .catch((reason) => {
        if (!cancelled) {
          setEvidenceError(message(reason, '新闻证据加载失败。'))
          setEvidenceLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [activeTab, evidence, runId])

  useEffect(() => {
    if (activeTab !== 'quality' || quality) return
    let cancelled = false
    setQualityLoading(true)
    fetchDataRunQuality(runId)
      .then((value) => {
        if (!cancelled) { setQuality(value); setQualityError(null); setQualityLoading(false) }
      })
      .catch((reason) => {
        if (!cancelled) {
          setQualityError(message(reason, '质量报告加载失败。'))
          setQualityLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [activeTab, quality, runId])

  const generate = async () => {
    setActionBusy(true)
    setActionError(null)
    try {
      const result = await generateDataRunArticle(runId)
      setContentRun({
        run_id: result.run_id,
        status: 'RUNNING',
        draft_id: null,
        can_view_draft: false,
        requested_at: new Date().toISOString(),
        finished_at: null,
      })
    } catch (reason) {
      setActionError(message(reason, '分析稿未能启动生成，请检查 LLM 配置后重试。'))
    } finally {
      setActionBusy(false)
    }
  }

  const retry = async () => {
    setActionBusy(true)
    setActionError(null)
    try {
      const result = await retryDataRun(runId)
      navigate(`/data-runs/${result.run_id}`)
    } catch (reason) {
      setActionError(message(reason, '无法创建重试运行。'))
    } finally {
      setActionBusy(false)
    }
  }

  if (loading) return <LoadingState label="正在加载数据运行…" />
  if (runError && !run) return <InlineAlert tone="error" title="无法加载数据运行">{runError}<div><button className="button button-secondary" type="button" onClick={() => void loadRun()}>重新加载</button></div></InlineAlert>
  if (!run) return null

  const tabs: Array<{ id: WorkbenchTab; label: string }> = [
    { id: 'market', label: '行情板块' },
    { id: 'candidates', label: '候选板块' },
    { id: 'evidence', label: '新闻证据' },
    { id: 'quality', label: '质量报告' },
  ]

  return <section>
    <PageHeader title={run.mode === 'post_close' ? '盘后数据运行' : '盘中数据运行'} description={`运行 ${run.run_id.slice(0, 8)} · ${formatDate(run.requested_at)}`} actions={<Link className="button button-secondary" to="/runs">返回运行历史</Link>} />
    <div className="detail-summary data-run-summary"><div><span>状态</span><StatusBadge status={run.status} /></div><div><span>场景</span><strong>{run.mode === 'post_close' ? '盘后复盘' : '盘中分析'}</strong></div><div><span>Provider</span><strong>{run.provider ?? '尚未记录'}</strong></div><div><span>Cutoff</span><strong>{run.cutoff_at ? formatDate(run.cutoff_at) : '尚未产生'}</strong></div><div><span>候选板块</span><strong>{candidatesLoading ? '加载中' : candidates.length || '尚未产生'}</strong></div><div><span>完成时间</span><strong>{run.finished_at ? formatDate(run.finished_at) : '尚未完成'}</strong></div></div>
    {runError && <InlineAlert tone="warning" title="刷新未完成">{runError}</InlineAlert>}
    {run.downgrade_reasons.length > 0 && <InlineAlert tone="warning" title="本次运行存在数据降级"><ul>{run.downgrade_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></InlineAlert>}
    <Panel title="数据处理进度" description="阶段状态来自已持久化的运行记录，刷新页面后仍可恢复。"><DataRunTimeline run={run} /></Panel>
    <DataRunActionPanel run={run} contentRun={contentRun} busy={actionBusy} error={actionError} onGenerate={() => void generate()} onRetry={() => void retry()} />
    <div className="workbench-tabs" role="tablist" aria-label="数据运行详情">{tabs.map((tab) => <button key={tab.id} id={`tab-${tab.id}`} role="tab" type="button" aria-selected={activeTab === tab.id} aria-controls={`panel-${tab.id}`} onClick={() => setActiveTab(tab.id)}>{tab.label}</button>)}</div>
    <Panel className="data-workbench-panel"><div id={`panel-${activeTab}`} role="tabpanel" aria-labelledby={`tab-${activeTab}`}>
      {activeTab === 'market' && <MarketPanel data={market} kind={marketKind} loading={marketLoading} error={marketError} onKindChange={(kind) => { setMarketKind(kind); setMarketOffset(0) }} onPage={setMarketOffset} />}
      {activeTab === 'candidates' && <CandidatesPanel candidates={candidates} loading={candidatesLoading} error={candidatesError} />}
      {activeTab === 'evidence' && <EvidencePanel data={evidence} loading={evidenceLoading} error={evidenceError} />}
      {activeTab === 'quality' && <QualityPanel data={quality} loading={qualityLoading} error={qualityError} />}
    </div></Panel>
  </section>
}
