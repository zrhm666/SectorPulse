import { useCallback, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { fetchDataRun } from '../dataRunsApi'
import Button from '../components/ui/Button'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import StatusBadge from '../components/ui/StatusBadge'
import SummaryStrip from '../components/ui/SummaryStrip'
import useRunComparison from '../hooks/useRunComparison'
import useComparisonRequest from '../hooks/useComparisonRequest'
import type { ComparisonPair, ComparisonTab, RunOption } from '../runComparisonsApi'
import { formatDate } from '../runPresentation'
import RunPickerDialog from './run-comparison/RunPickerDialog'
import { kindLabel, QueryError } from './run-comparison/ComparisonShared'
import SectorComparisonPanel from './run-comparison/SectorComparisonPanel'
import NewsComparisonPanel from './run-comparison/NewsComparisonPanel'
import EvidenceComparisonPanel from './run-comparison/EvidenceComparisonPanel'
import '../styles/run-comparison.css'

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const tabs: Array<{ id: ComparisonTab; label: string }> = [
  { id: 'sectors', label: '候选与行情' }, { id: 'news', label: '新闻记录' }, { id: 'evidence', label: '板块证据' },
]
type Selection = { base: RunOption | null; compare: RunOption | null }

function SelectionSide({ side, run, rawId, choose }: { side: 'base' | 'compare'; run: RunOption | null; rawId: string; choose: () => void }) {
  const label = side === 'base' ? '基准 A' : '对照 B'
  return <div className="comparison-selection__side" aria-label={label}>
    <div className="comparison-selection__title"><h3>{label}</h3><Button variant="secondary" onClick={choose}>选择{side === 'base' ? '基准' : '对照'}运行</Button></div>
    {run ? <><strong className="comparison-selection__date">{formatDate(run.requested_at)}</strong>
      <div className="comparison-run-meta"><span>{run.provider} · {run.mode === 'post_close' ? '盘后复盘' : '盘中分析'}</span><StatusBadge status={run.status} /></div>
      <code title={run.run_id}>{run.run_id}</code>
      <dl className="comparison-context"><dt>数据截点</dt><dd>{run.cutoff_at ? formatDate(run.cutoff_at) : '未保存'}</dd><dt>新闻窗口</dt><dd>{run.lookback_hours} 小时</dd><dt>候选上限</dt><dd>预选 {run.precandidate_limit} / 最终 {run.final_candidate_limit}</dd></dl>
      <Link to={`/data-runs/${run.run_id}`}>查看原运行</Link>
    </> : <div className="comparison-selection__empty"><p>{rawId ? '已从链接选择运行，等待读取或重新选择。' : '选择一次已结束的数据运行。'}</p>{rawId && <code>{rawId}</code>}</div>}
  </div>
}

function Workspace({ baseId, compareId, tab, commit, changeTab }: {
  baseId: string; compareId: string; tab: ComparisonTab
  commit: (pair: ComparisonPair) => void; changeTab: (tab: ComparisonTab) => void
}) {
  const invalid = (!!baseId && !uuid.test(baseId)) || (!!compareId && !uuid.test(compareId))
    ? '运行 ID 格式无效，请重新选择运行。' : baseId && baseId === compareId ? '请选择两次不同的数据运行。' : null
  const pair = !invalid && baseId && compareId ? { base: baseId, compare: compareId } : null
  const query = useRunComparison(pair)
  const loneId = !invalid && (!!baseId !== !!compareId) ? baseId || compareId : null
  const prefill = useCallback(async (signal: AbortSignal): Promise<RunOption> => {
    const run = await fetchDataRun(loneId!, signal)
    if (!run.provider || !run.request) throw new Error('该历史运行缺少来源或请求配置，请从列表重新选择。')
    return { ...run.request, run_id: run.run_id, provider: run.provider, mode: run.mode, status: run.status,
      requested_at: run.requested_at, cutoff_at: run.cutoff_at ?? null, finished_at: run.finished_at ?? null, error_code: run.error_code ?? null }
  }, [loneId])
  const prefillQuery = useComparisonRequest(loneId, prefill)
  const [draft, setDraft] = useState<Selection | null>(null)
  const selected: Selection = draft ?? {
    base: query.data?.base ?? (baseId ? prefillQuery.data : null),
    compare: query.data?.compare ?? (compareId ? prefillQuery.data : null),
  }
  const [picker, setPicker] = useState<'base' | 'compare' | null>(null)
  const [selectionNotice, setSelectionNotice] = useState<string | null>(null)
  const compatible = selected.base && selected.compare && selected.base.run_id !== selected.compare.run_id
    && selected.base.provider === selected.compare.provider && selected.base.mode === selected.compare.mode
  const submitted = selected.base?.run_id === baseId && selected.compare?.run_id === compareId
  const selectionReason = compatible ? null : !selected.base || !selected.compare ? '请选择基准和对照两次运行。' : '需要两次不同且来源、场景相同的运行。'
  const select = (run: RunOption) => {
    if (!picker) return
    const otherSide = picker === 'base' ? 'compare' : 'base'
    const other = selected[otherSide]
    const mismatch = other && (other.provider !== run.provider || other.mode !== run.mode || other.run_id === run.run_id)
    setDraft({ ...selected, [picker]: run, [otherSide]: mismatch ? null : other })
    setSelectionNotice(mismatch ? '另一侧与新选择不兼容，已清空，请重新选择。' : null)
    setPicker(null)
  }
  const swap = () => {
    if (!selected.base || !selected.compare) return
    if (submitted) commit({ base: selected.compare.run_id, compare: selected.base.run_id })
    else setDraft({ base: selected.compare, compare: selected.base })
  }
  const data = submitted ? query.data : null
  return <section className="run-comparison-page density-compact">
    <PageHeader title="运行对比" description="对齐两次已保存的候选、行情与新闻证据。不重新采集数据。" actions={<Link className="button button-secondary" to="/runs">返回运行历史</Link>} />
    <Panel title="选择对比运行" density="compact" description="同一来源、同一场景；A 为基准，B 为对照。">
      <div className="comparison-selection">
        <SelectionSide side="base" run={selected.base} rawId={baseId} choose={() => setPicker('base')} />
        <Button className="comparison-swap" variant="ghost" disabled={!compatible} onClick={swap} aria-label="交换基准与对照">交换</Button>
        <SelectionSide side="compare" run={selected.compare} rawId={compareId} choose={() => setPicker('compare')} />
      </div>
      <div className="comparison-selection__footer"><p aria-live="polite">{selectionNotice ?? selectionReason ?? (submitted ? '差值方向：对照 B − 基准 A。排名单独按上升 / 下降说明。' : '选择已更改，点击开始对比后应用。')}</p>
        <Button disabled={!compatible} onClick={() => submitted ? query.reload() : commit({ base: selected.base!.run_id, compare: selected.compare!.run_id })}>开始对比</Button></div>
    </Panel>
    {invalid && <InlineAlert tone="error" title="无法使用当前链接">{invalid}</InlineAlert>}
    {prefillQuery.loading && <LoadingState label="正在读取预选运行…" />}
    {prefillQuery.error && <QueryError title="预选运行读取失败" error={prefillQuery.error} retry={prefillQuery.reload} />}
    {query.loading && <LoadingState label="正在对比已保存记录…" />}
    {query.error && <QueryError title="运行对比失败" error={query.error} retry={query.reload} label="重试对比" />}
    {!pair && !invalid && !prefillQuery.loading && <p className="comparison-note">选择器可翻阅全部已结束运行；不足两次时，请先<Link to="/runs">查看运行历史</Link>或<Link to="/runs/new">新建分析</Link>。</p>}
    {data && <>
      {data.warnings.length > 0 && <aside className="comparison-notes" aria-label="对比口径说明"><h2>对比口径</h2><ul>{data.warnings.map((warning, index) => <li key={`${warning.code}-${index}`}>{warning.side !== 'BOTH' && `${warning.side === 'BASE' ? '基准 A' : '对照 B'} · `}{warning.kind && `${kindLabel[warning.kind]} · `}{warning.message}</li>)}</ul></aside>}
      <SummaryStrip label="候选比较摘要" items={[
        { label: '两次均入选', value: data.candidates.both }, { label: '仅基准入选', value: data.candidates.only_base },
        { label: '仅对照入选', value: data.candidates.only_compare }, { label: '不可比类别', value: data.candidates.unavailable_kinds },
      ]} />
      <div className="comparison-tabs" role="tablist" aria-label="比较内容">{tabs.map((item, index) => <button key={item.id} type="button" role="tab" id={`comparison-tab-${item.id}`} aria-controls={`comparison-panel-${item.id}`} aria-selected={tab === item.id} tabIndex={tab === item.id ? 0 : -1} onClick={() => changeTab(item.id)} onKeyDown={(event) => {
        const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null
        if (next === null) return
        event.preventDefault(); changeTab(tabs[next].id); document.getElementById(`comparison-tab-${tabs[next].id}`)?.focus()
      }}>{item.label}</button>)}</div>
      <div role="tabpanel" id={`comparison-panel-${tab}`} aria-labelledby={`comparison-tab-${tab}`} tabIndex={0}>
        <p className="comparison-note">查询时间：{formatDate(data.queried_at)}。本页仅查看留存记录，不会触发采集或写作。</p>
        {tab === 'sectors' && <SectorComparisonPanel data={data} />}
        {tab === 'news' && <NewsComparisonPanel pair={{ base: baseId, compare: compareId }} />}
        {tab === 'evidence' && <EvidenceComparisonPanel pair={{ base: baseId, compare: compareId }} />}
      </div>
    </>}
    {picker && <RunPickerDialog key={picker} title={picker === 'base' ? '选择基准运行' : '选择对照运行'} constraint={selected[picker === 'base' ? 'compare' : 'base']} excludedRunId={selected[picker === 'base' ? 'compare' : 'base']?.run_id ?? null} onSelect={select} onClose={() => setPicker(null)} />}
  </section>
}

export default function RunComparisonPage() {
  const [params, setParams] = useSearchParams()
  const baseId = (params.get('base') ?? '').toLowerCase(), compareId = (params.get('compare') ?? '').toLowerCase()
  const rawTab = params.get('tab'), tab: ComparisonTab = rawTab === 'news' || rawTab === 'evidence' ? rawTab : 'sectors'
  return <Workspace key={JSON.stringify([baseId, compareId])} baseId={baseId} compareId={compareId} tab={tab}
    commit={(pair) => setParams({ ...pair, tab })}
    changeTab={(value) => { const next = new URLSearchParams(params); next.set('tab', value); setParams(next) }} />
}
