import { useState } from 'react'
import Panel from '../../components/ui/Panel'
import type { RunComparisonView, SectorComparisonRow, SectorKind } from '../../runComparisonsApi'
import { kindLabel, missingLabel } from './ComparisonShared'

function value(metric: SectorComparisonRow['pct_change'], field: 'base' | 'compare' | 'delta') {
  const raw = metric[field]
  if (raw === null) return metric[`${field}_reason` as 'base_reason' | 'compare_reason'] ? missingLabel[metric[`${field}_reason` as 'base_reason' | 'compare_reason']!] : '—'
  return raw
}
function change(metric: SectorComparisonRow['pct_change']) {
  if (metric.delta === null) return value(metric, 'delta')
  return `${Number(metric.delta) > 0 ? '+' : ''}${metric.delta}${metric.unit === 'percentage_points' ? ' 个百分点' : ' 家'}`
}
function Row({ row }: { row: SectorComparisonRow }) {
  const [expanded, setExpanded] = useState(false)
  const detailsId = `sector-details-${row.kind}-${row.sector_id}`
  return <>
    <tr>
      <th scope="row"><span className="comparison-sector-name">{row.base_name ?? row.compare_name ?? row.sector_id}</span><small>{kindLabel[row.kind]} · {row.sector_id}</small></th>
      <td>{row.base_rank ?? '未入选'}</td><td>{row.compare_rank ?? '未入选'}</td>
      <td>{row.rank_delta === null ? '—' : row.rank_delta > 0 ? `上升 ${row.rank_delta} 位` : row.rank_delta < 0 ? `下降 ${Math.abs(row.rank_delta)} 位` : '无变化'}</td>
      <td>{value(row.pct_change, 'base')}%</td><td>{value(row.pct_change, 'compare')}%</td><td>{change(row.pct_change)}</td>
      <td><span className={`comparison-membership comparison-membership--${row.membership.toLowerCase()}`}>{row.membership === 'BOTH' ? '两次均入选' : row.membership === 'ONLY_BASE' ? '仅基准入选' : '仅对照入选'}</span><button type="button" className="comparison-details-button" aria-expanded={expanded} aria-controls={detailsId} onClick={() => setExpanded((current) => !current)}>{expanded ? '收起详情' : '查看详情'}</button></td>
    </tr>
    {expanded && <tr id={detailsId} className="comparison-detail-row"><td colSpan={8}><dl><dt>基准 A 换手率</dt><dd>{value(row.turnover_rate, 'base')}</dd><dt>对照 B 换手率</dt><dd>{value(row.turnover_rate, 'compare')}</dd><dt>涨跌家数</dt><dd>A {value(row.advancers, 'base')} / {value(row.decliners, 'base')} · B {value(row.advancers, 'compare')} / {value(row.decliners, 'compare')}</dd><dt>相对分</dt><dd>A {row.base_score ?? '未入选'} / B {row.compare_score ?? '未入选'}。各次运行内部相对分，不代表跨运行绝对强弱。</dd></dl></td></tr>}
  </>
}
export default function SectorComparisonPanel({ data }: { data: RunComparisonView }) {
  const [kind, setKind] = useState<'ALL' | SectorKind>('ALL')
  const groups = data.kinds.filter((group) => kind === 'ALL' || group.kind === kind)
  return <Panel title="候选与行情" description="系统候选按板块类型和运行方向对齐；差值为对照 B − 基准 A。" density="compact">
    <label className="comparison-inline-filter">板块类型<select aria-label="板块类型" value={kind} onChange={(event) => setKind(event.target.value as 'ALL' | SectorKind)}><option value="ALL">全部板块</option><option value="INDUSTRY">行业</option><option value="CONCEPT">概念</option></select></label>
    {groups.map((group) => <section className="comparison-kind-group" key={group.kind} aria-label={kindLabel[group.kind]}><header><h3>{kindLabel[group.kind]}</h3><span>{group.status === 'COMPARABLE' ? `${group.rows.length} 条候选` : group.status === 'INCOMPATIBLE' ? '来源或分类版本不一致' : '缺少行情快照'}</span></header>{group.status === 'COMPARABLE' && group.rows.length > 0 ? <div className="comparison-table-wrap"><table className="comparison-table"><caption>{kindLabel[group.kind]}候选与行情</caption><thead><tr><th scope="col">板块</th><th scope="col">基准 A 排名</th><th scope="col">对照 B 排名</th><th scope="col">排名变化</th><th scope="col">A 涨跌幅</th><th scope="col">B 涨跌幅</th><th scope="col">差值</th><th scope="col">入选关系</th></tr></thead><tbody>{group.rows.map((row) => <Row key={`${row.kind}-${row.sector_id}`} row={row} />)}</tbody></table></div> : <p className="comparison-empty">当前筛选没有可比候选；保留原始分类状态，不强行配对板块。</p>}</section>)}
  </Panel>
}
