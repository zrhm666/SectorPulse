import { useId, useState } from 'react'
import Panel from '../../components/ui/Panel'
import type { MetricDifference, MembershipFilter, RunComparisonView, SectorComparisonRow, SectorKind, SnapshotContext } from '../../runComparisonsApi'
import { formatDate } from '../../runPresentation'
import { kindLabel, missingLabel } from './ComparisonShared'

function value(metric: MetricDifference, side: 'base' | 'compare') {
  const raw = metric[side]
  if (raw === null) return missingLabel[metric[`${side}_reason`] ?? 'VALUE_MISSING']
  return `${raw}${metric.unit === 'percentage_points' ? '%' : ' 家'}`
}

function change(metric: MetricDifference) {
  if (metric.delta === null) return '—'
  const positive = !metric.delta.startsWith('-') && /[1-9]/.test(metric.delta)
  return `${positive ? '+' : ''}${metric.delta}${metric.unit === 'percentage_points' ? ' 个百分点' : ' 家'}`
}

function SnapshotDetails({ label, context }: { label: string; context: SnapshotContext | null }) {
  return <div><h4>{label}</h4>{context ? <dl className="comparison-context">
    <dt>数据来源</dt><dd>{context.provider_id || '未保存'}</dd>
    <dt>分类版本</dt><dd>{context.classification_version || '未保存'}</dd>
    <dt>采集程序版本</dt><dd>{context.source_version || '未保存'}</dd>
    <dt>观测时间</dt><dd>{formatDate(context.observed_at)}</dd>
    <dt>采集时间</dt><dd>{formatDate(context.collected_at)}</dd>
    <dt>实际字段</dt><dd>{context.available_fields.join('、') || '字段口径未知'}</dd>
  </dl> : <p>未留存行情快照</p>}</div>
}

function Row({ row }: { row: SectorComparisonRow }) {
  const [expanded, setExpanded] = useState(false)
  const detailsId = useId()
  return <>
    <tr>
      <th scope="row"><span className="comparison-sector-name">{row.base_name ?? row.compare_name ?? row.sector_id}</span><small>{kindLabel[row.kind]} · {row.sector_id}</small></th>
      <td data-label="基准 A 排名">{row.base_rank ?? '未入选'}</td>
      <td data-label="对照 B 排名">{row.compare_rank ?? '未入选'}</td>
      <td data-label="排名变化">{row.rank_delta === null ? '—' : row.rank_delta > 0 ? `上升 ${row.rank_delta} 位` : row.rank_delta < 0 ? `下降 ${Math.abs(row.rank_delta)} 位` : '无变化'}</td>
      <td data-label="A 涨跌幅">{value(row.pct_change, 'base')}</td>
      <td data-label="B 涨跌幅">{value(row.pct_change, 'compare')}</td>
      <td data-label="差值">{change(row.pct_change)}</td>
      <td data-label="入选关系"><span className="comparison-membership">{row.membership === 'BOTH' ? '两次均入选' : row.membership === 'ONLY_BASE' ? '仅基准入选' : '仅对照入选'}</span><button type="button" className="comparison-details-button" aria-expanded={expanded} aria-controls={detailsId} onClick={() => setExpanded((current) => !current)}>{expanded ? '收起详情' : '查看详情'}</button></td>
    </tr>
    {expanded && <tr id={detailsId} className="comparison-detail-row"><td colSpan={8}><dl>
      <dt>板块名称</dt><dd>A：{row.base_name ?? '未保存'} / B：{row.compare_name ?? '未保存'}</dd>
      <dt>领涨股 A / B</dt><dd><span>{row.base_leader ?? '未保存'}</span> / <span>{row.compare_leader ?? '未保存'}</span></dd>
      <dt>基准 A 换手率</dt><dd>{value(row.turnover_rate, 'base')}</dd>
      <dt>对照 B 换手率</dt><dd>{value(row.turnover_rate, 'compare')}</dd>
      <dt>换手率差值</dt><dd>{change(row.turnover_rate)}</dd>
      <dt>上涨家数 A / B</dt><dd>{value(row.advancers, 'base')} / {value(row.advancers, 'compare')}；差值 {change(row.advancers)}</dd>
      <dt>下跌家数 A / B</dt><dd>{value(row.decliners, 'base')} / {value(row.decliners, 'compare')}；差值 {change(row.decliners)}</dd>
      <dt>相对分</dt><dd>A {row.base_score ?? '未入选'} / B {row.compare_score ?? '未入选'}。各次运行内部相对分，不代表跨运行绝对强弱。</dd>
    </dl></td></tr>}
  </>
}

export default function SectorComparisonPanel({ data }: { data: RunComparisonView }) {
  const [kind, setKind] = useState<'ALL' | SectorKind>('ALL')
  const [membership, setMembership] = useState<MembershipFilter>('ALL')
  const groups = data.kinds.filter((group) => kind === 'ALL' || group.kind === kind)
  return <Panel title="候选与行情" description="系统候选按板块类型和运行方向对齐；差值为对照 B − 基准 A。" density="compact">
    <div className="comparison-panel-toolbar">
      <label>板块类型<select value={kind} onChange={(event) => setKind(event.target.value as 'ALL' | SectorKind)}><option value="ALL">全部板块</option><option value="INDUSTRY">行业</option><option value="CONCEPT">概念</option></select></label>
      <label>入选关系<select value={membership} onChange={(event) => setMembership(event.target.value as MembershipFilter)}><option value="ALL">全部关系</option><option value="BOTH">两次均入选</option><option value="ONLY_BASE">仅基准入选</option><option value="ONLY_COMPARE">仅对照入选</option></select></label>
    </div>
    {groups.map((group) => {
      const rows = group.rows.filter((row) => membership === 'ALL' || row.membership === membership)
      return <section className="comparison-kind-group" key={group.kind} aria-label={kindLabel[group.kind]}>
        <header><h3>{kindLabel[group.kind]}</h3><span>{group.status === 'COMPARABLE' ? `${rows.length} 条候选` : group.status === 'INCOMPATIBLE' ? '来源或分类版本不一致' : '缺少行情快照'}</span></header>
        <details className="comparison-snapshot-details"><summary>查看{kindLabel[group.kind]}来源与字段口径</summary><div className="comparison-snapshot-pair"><SnapshotDetails label="基准 A" context={group.base} /><SnapshotDetails label="对照 B" context={group.compare} /></div></details>
        {group.status === 'COMPARABLE' && rows.length > 0 ? <div className="comparison-table-wrap"><table className="comparison-table"><caption>{kindLabel[group.kind]}候选与行情</caption><thead><tr><th scope="col">板块</th><th scope="col">基准 A 排名</th><th scope="col">对照 B 排名</th><th scope="col">排名变化</th><th scope="col">A 涨跌幅</th><th scope="col">B 涨跌幅</th><th scope="col">差值</th><th scope="col">入选关系</th></tr></thead><tbody>{rows.map((row) => <Row key={`${row.kind}-${row.sector_id}`} row={row} />)}</tbody></table></div> : <p className="comparison-empty">当前筛选没有可比候选；保留原始分类状态，不强行配对板块。</p>}
      </section>
    })}
  </Panel>
}
