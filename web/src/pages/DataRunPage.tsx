import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import {
  type DataRunCandidateView,
  type DataRunCandidatePageView,
  type DataRunSelectionView,
  type CandidateSort,
  type SortDirection,
  type DataRunAcquisitionView,
  type DataRunContentView,
  type DataRunEvidenceView,
  type DataRunMarketView,
  type DataRunNewsRecordsView,
  type DataRunQualityView,
  type DataRunView,
  type DataStatus,
  type SectorKind,
  fetchDataRun,
  fetchDataRunAcquisition,
  fetchDataRunCandidatePage,
  fetchDataRunSelection,
  confirmDataRunSelection,
  fetchDataRunContentRun,
  fetchDataRunEvidence,
  fetchDataRunMarket,
  fetchDataRunNewsRecords,
  fetchDataRunQuality,
  generateDataRunArticle,
  retryDataRun,
} from '../dataRunsApi'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import StatusBadge from '../components/ui/StatusBadge'
import SummaryStrip from '../components/ui/SummaryStrip'
import { formatDate } from '../runPresentation'
import CandidatesPanel from './data-run/CandidatesPanel'
import CandidateSelectionBar from './data-run/CandidateSelectionBar'
import AcquisitionSummary from './data-run/AcquisitionSummary'
import DataRunActionPanel from './data-run/DataRunActionPanel'
import DataRunTimeline from './data-run/DataRunTimeline'
import EvidencePanel from './data-run/EvidencePanel'
import MarketPanel from './data-run/MarketPanel'
import NewsRecordsPanel from './data-run/NewsRecordsPanel'
import QualityPanel from './data-run/QualityPanel'

const TERMINAL_STATUSES = new Set([
  'READY_FOR_ATTRIBUTION', 'DEGRADED', 'BLOCKED', 'FAILED',
  'CANCELLED', 'INTERRUPTED',
])
type WorkbenchTab = 'market' | 'candidates' | 'news-records' | 'evidence' | 'quality'

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
  const [candidatePage, setCandidatePage] = useState<DataRunCandidatePageView | null>(null)
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([])
  const [selection, setSelection] = useState<DataRunSelectionView | null>(null)
  const [selectionSaving, setSelectionSaving] = useState(false)
  const [selectionConflict, setSelectionConflict] = useState(false)
  const [candidateQuery, setCandidateQuery] = useState('')
  const [candidateSort, setCandidateSort] = useState<CandidateSort>('rank')
  const [candidateDirection, setCandidateDirection] = useState<SortDirection>('asc')
  const [candidateOffset, setCandidateOffset] = useState(0)
  const [candidatesLoading, setCandidatesLoading] = useState(true)
  const [candidatesError, setCandidatesError] = useState<string | null>(null)
  const [contentRun, setContentRun] = useState<DataRunContentView | null>(null)
  const [acquisition, setAcquisition] = useState<DataRunAcquisitionView | null>(null)
  const [acquisitionLoading, setAcquisitionLoading] = useState(true)
  const [acquisitionError, setAcquisitionError] = useState<string | null>(null)
  const [marketKind, setMarketKind] = useState<SectorKind>('INDUSTRY')
  const [marketOffset, setMarketOffset] = useState(0)
  const [market, setMarket] = useState<DataRunMarketView | null>(null)
  const [marketLoading, setMarketLoading] = useState(true)
  const [marketError, setMarketError] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<DataRunEvidenceView | null>(null)
  const [evidenceLoading, setEvidenceLoading] = useState(false)
  const [evidenceError, setEvidenceError] = useState<string | null>(null)
  const [newsRecords, setNewsRecords] = useState<DataRunNewsRecordsView | null>(null)
  const [newsRecordsLoading, setNewsRecordsLoading] = useState(false)
  const [newsRecordsError, setNewsRecordsError] = useState<string | null>(null)
  const [newsSourceId, setNewsSourceId] = useState('')
  const [newsStatus, setNewsStatus] = useState<'' | DataStatus>('')
  const [newsOffset, setNewsOffset] = useState(0)
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
      const page = await fetchDataRunCandidatePage(runId, {
        query: candidateQuery || undefined,
        sort: candidateSort,
        direction: candidateDirection,
        offset: candidateOffset,
        limit: 20,
      })
      setCandidatePage(page)
      setCandidates(page.items)
      setCandidatesError(null)
    } catch (reason) {
      setCandidatesError(message(reason, '候选板块加载失败。'))
    } finally {
      setCandidatesLoading(false)
    }
  }, [candidateDirection, candidateOffset, candidateQuery, candidateSort, runId])

  const loadSelection = useCallback(async () => {
    try {
      const value = await fetchDataRunSelection(runId)
      setSelection(value)
      setSelectedCandidateIds(value.selected_sector_ids)
    } catch (reason) {
      setCandidatesError(message(reason, '候选确认状态加载失败。'))
    }
  }, [runId])

  const loadAcquisition = useCallback(async () => {
    setAcquisitionLoading(true)
    try {
      setAcquisition(await fetchDataRunAcquisition(runId))
      setAcquisitionError(null)
    } catch (reason) {
      setAcquisitionError(message(reason, '采集记录加载失败。'))
    } finally {
      setAcquisitionLoading(false)
    }
  }, [runId])

  useEffect(() => {
    setRun(null)
    setCandidates([])
    setCandidatePage(null)
    setSelectedCandidateIds([])
    setSelection(null)
    setSelectionConflict(false)
    setContentRun(null)
    setAcquisition(null)
    setEvidence(null)
    setQuality(null)
    setMarket(null)
    setNewsRecords(null)
    setNewsSourceId('')
    setNewsStatus('')
    setNewsOffset(0)
    setActionError(null)
    void loadRun()
    void loadAcquisition()
    void loadSelection()
    fetchDataRunContentRun(runId).then(setContentRun).catch(() => setContentRun(null))
  }, [loadAcquisition, loadRun, loadSelection, runId])

  useEffect(() => {
    if (!run) return
    void loadCandidates()
  }, [loadCandidates, run?.status])

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
    if (activeTab !== 'news-records') return
    let cancelled = false
    setNewsRecordsLoading(true)
    fetchDataRunNewsRecords(runId, {
      sourceId: newsSourceId || undefined,
      status: newsStatus || undefined,
      offset: newsOffset,
      limit: 20,
    })
      .then((value) => { if (!cancelled) { setNewsRecords(value); setNewsRecordsError(null) } })
      .catch((reason) => { if (!cancelled) setNewsRecordsError(message(reason, '新闻记录加载失败。')) })
      .finally(() => { if (!cancelled) setNewsRecordsLoading(false) })
    return () => { cancelled = true }
  }, [activeTab, newsOffset, newsSourceId, newsStatus, runId])

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

  const normalizedSelected = [...selectedCandidateIds].sort()
  const normalizedConfirmed = [...(selection?.selected_sector_ids ?? [])].sort()
  const selectionDirty = normalizedSelected.join('\u0000') !== normalizedConfirmed.join('\u0000')
  const selectionDisabledReason = run?.status !== 'READY_FOR_ATTRIBUTION'
    ? '数据尚未进入候选确认阶段'
    : candidatesLoading
      ? '候选板块仍在加载'
      : selectedCandidateIds.length < 3
        ? '至少选择 3 个板块'
        : selectedCandidateIds.length > 12
          ? '最多选择 12 个板块'
          : null

  const confirmSelection = async () => {
    if (!selection || selectionDisabledReason) return
    setSelectionSaving(true)
    setCandidatesError(null)
    try {
      const value = await confirmDataRunSelection(
        runId,
        selectedCandidateIds,
        selection.version,
      )
      setSelection(value)
      setSelectedCandidateIds(value.selected_sector_ids)
      setSelectionConflict(false)
    } catch (reason) {
      if (reason instanceof Error && reason.message.includes('VERSION_CONFLICT')) {
        setSelectionConflict(true)
      }
      setCandidatesError(message(reason, '候选确认失败；本地选择已保留，请刷新版本后重试。'))
    } finally {
      setSelectionSaving(false)
    }
  }

  const reloadSelectionVersion = async () => {
    try {
      const value = await fetchDataRunSelection(runId)
      setSelection(value)
      setSelectionConflict(false)
      setCandidatesError(null)
    } catch (reason) {
      setCandidatesError(message(reason, '最新候选版本加载失败。'))
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
    { id: 'news-records', label: '新闻记录' },
    { id: 'evidence', label: '新闻证据' },
    { id: 'quality', label: '质量报告' },
  ]

  return <section className="data-run-page density-compact">
    <PageHeader title={run.mode === 'post_close' ? '盘后数据运行' : '盘中数据运行'} description={`运行 ${run.run_id.slice(0, 8)} · ${formatDate(run.requested_at)}`} actions={<Link className="button button-secondary" to="/runs">返回运行历史</Link>} />
    <SummaryStrip label="数据运行摘要" className="data-run-summary" items={[
      { label: '状态', value: <StatusBadge status={run.status} /> },
      { label: '场景', value: run.mode === 'post_close' ? '盘后复盘' : '盘中分析' },
      { label: 'Provider', value: run.provider ?? '尚未记录' },
      { label: 'Cutoff', value: run.cutoff_at ? formatDate(run.cutoff_at) : '尚未产生' },
      { label: '候选板块', value: candidatesLoading ? '加载中' : candidatePage?.total || '尚未产生' },
      { label: '完成时间', value: run.finished_at ? formatDate(run.finished_at) : '尚未完成' },
    ]} />
    {runError && <InlineAlert tone="warning" title="刷新未完成">{runError}</InlineAlert>}
    {run.downgrade_reasons.length > 0 && <InlineAlert tone="warning" title="本次运行存在数据降级"><ul>{run.downgrade_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></InlineAlert>}
    <Panel title="数据处理进度" description="阶段状态来自已持久化的运行记录，刷新页面后仍可恢复。"><DataRunTimeline run={run} /></Panel>
    <AcquisitionSummary data={acquisition} loading={acquisitionLoading} error={acquisitionError} />
    <DataRunActionPanel run={run} contentRun={contentRun} busy={actionBusy} error={actionError} candidateCount={selectedCandidateIds.length} candidatesLoading={candidatesLoading} selectionConfirmed={Boolean(selection?.confirmed)} selectionDirty={selectionDirty} onGenerate={() => void generate()} onRetry={() => void retry()} />
    <div className="workbench-tabs" role="tablist" aria-label="数据运行详情">{tabs.map((tab) => <button key={tab.id} id={`tab-${tab.id}`} role="tab" type="button" aria-selected={activeTab === tab.id} aria-controls={`panel-${tab.id}`} onClick={() => setActiveTab(tab.id)}>{tab.label}</button>)}</div>
    <Panel className="data-workbench-panel" density="compact"><div id={`panel-${activeTab}`} role="tabpanel" aria-labelledby={`tab-${activeTab}`}>
      {activeTab === 'market' && <MarketPanel data={market} kind={marketKind} loading={marketLoading} error={marketError} onKindChange={(kind) => { setMarketKind(kind); setMarketOffset(0) }} onPage={setMarketOffset} />}
      {activeTab === 'candidates' && <CandidatesPanel
        page={candidatePage}
        selectedIds={selectedCandidateIds}
        loading={candidatesLoading}
        error={candidatesError}
        disabled={actionBusy || Boolean(contentRun) || run.status !== 'READY_FOR_ATTRIBUTION'}
        onToggle={(sectorId) => setSelectedCandidateIds((current) => current.includes(sectorId)
          ? current.filter((item) => item !== sectorId)
          : [...current, sectorId])}
        query={candidateQuery}
        sort={candidateSort}
        direction={candidateDirection}
        onSelectPage={() => setSelectedCandidateIds((current) => Array.from(new Set([...current, ...candidates.map((item) => item.sector_id)])))}
        onClear={() => setSelectedCandidateIds([])}
        onQueryChange={(value) => { setCandidateQuery(value); setCandidateOffset(0) }}
        onSortChange={(value) => { setCandidateSort(value); setCandidateOffset(0) }}
        onDirectionChange={(value) => { setCandidateDirection(value); setCandidateOffset(0) }}
        onPage={setCandidateOffset}
      />}
      {activeTab === 'news-records' && <NewsRecordsPanel data={newsRecords} loading={newsRecordsLoading} error={newsRecordsError} sourceId={newsSourceId} status={newsStatus} sourceOptions={acquisition?.news_sources.map((source) => source.source_id) ?? []} onSourceChange={(value) => { setNewsSourceId(value); setNewsOffset(0) }} onStatusChange={(value) => { setNewsStatus(value); setNewsOffset(0) }} onPage={setNewsOffset} />}
      {activeTab === 'evidence' && <EvidencePanel data={evidence} loading={evidenceLoading} error={evidenceError} />}
      {activeTab === 'quality' && <QualityPanel data={quality} loading={qualityLoading} error={qualityError} />}
    </div></Panel>
    {activeTab === 'candidates' && <CandidateSelectionBar selectedCount={selectedCandidateIds.length} confirmedVersion={selection?.confirmed ? selection.version : null} dirty={selectionDirty} saving={selectionSaving} disabledReason={selectionDisabledReason} conflict={selectionConflict} onConfirm={() => void confirmSelection()} onReset={() => setSelectedCandidateIds(selection?.selected_sector_ids ?? [])} onReloadVersion={() => void reloadSelectionVersion()} />}
  </section>
}
