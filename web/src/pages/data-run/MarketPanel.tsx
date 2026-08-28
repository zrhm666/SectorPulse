import type { DataRunMarketView, MarketSectorView, SectorKind } from '../../dataRunsApi'
import { marketCapability } from './marketCapability'

type Props = {
  data: DataRunMarketView | null
  kind: SectorKind
  loading: boolean
  error: string | null
  onKindChange: (kind: SectorKind) => void
  onPage: (offset: number) => void
  onOpenDetail: (item: MarketSectorView) => void
}

export default function MarketPanel({ data, kind, loading, error, onKindChange, onPage, onOpenDetail }: Props) {
  const summary = data?.snapshots.find((item) => item.kind === kind)
  const capability = summary ? marketCapability(summary) : null
  const display = (availability: boolean | undefined, value: string | number | null, suffix = '') => {
    if (availability === false) return '未返回'
    if (value == null) return '未返回'
    return `${value}${suffix}`
  }
  return <div>
    <div className="data-run-toolbar">
      <div className="segmented-control" aria-label="板块类型">
        {(['INDUSTRY', 'CONCEPT'] as const).map((item) => <button key={item} type="button" data-active={kind === item} onClick={() => onKindChange(item)}>{item === 'INDUSTRY' ? '行业' : '概念'}</button>)}
      </div>
      {summary && <div className="market-source-meta">
        <p>{summary.provider_id} · {summary.sector_count} 个板块 · 实际字段 {summary.available_fields?.length ?? '历史未记录'} · 观测 {new Date(summary.observed_at).toLocaleString('zh-CN')}</p>
        {capability && <p><span className="market-capability-badge" data-capability={capability.level}>{capability.label}</span>{capability.notice && <small>{capability.notice}</small>}</p>}
      </div>}
    </div>
    {loading && <p className="status-detail">正在加载行情板块…</p>}
    {error && <p className="panel-error" role="alert">{error}</p>}
    {!loading && !error && (!data || data.items.length === 0) && <p className="status-detail">行情板块尚未产生，当前运行可能仍在采集阶段。</p>}
    {data && data.items.length > 0 && <>
      <p className="field-coverage-notice">“未返回”表示该 Provider 的响应里没有这个字段；真实的零值会显示为 0。</p>
      <div className="run-table-wrap"><table className="run-table"><thead><tr><th>板块</th><th>涨跌幅</th><th>换手率</th><th>上涨/下跌</th><th>领涨股</th><th>领涨幅</th><th>详情</th></tr></thead><tbody>{data.items.map((item) => {
        const fields = item.field_availability ?? {}
        const breadth = fields.advancers === false || fields.decliners === false ? '未返回' : `${item.advancers}/${item.decliners}`
        return <tr key={item.sector_id}><td data-label="板块"><strong>{item.name}</strong><small>{item.sector_id}</small></td><td data-label="涨跌幅">{display(fields.pct_change, item.pct_change, '%')}</td><td data-label="换手率">{display(fields.turnover_rate, item.turnover_rate, '%')}</td><td data-label="上涨/下跌">{breadth}</td><td data-label="领涨股">{display(fields.leader_name, item.leader_name)}</td><td data-label="领涨幅">{display(fields.leader_pct_change, item.leader_pct_change, '%')}</td><td data-label="详情"><button className="button button-ghost" type="button" onClick={() => onOpenDetail(item)}>查看详情</button></td></tr>
      })}</tbody></table></div>
      <div className="pagination"><button className="button button-secondary" type="button" disabled={data.offset === 0} onClick={() => onPage(Math.max(0, data.offset - data.limit))}>上一页</button><span>{data.offset + 1}–{Math.min(data.offset + data.limit, data.total)} / {data.total}</span><button className="button button-secondary" type="button" disabled={data.offset + data.limit >= data.total} onClick={() => onPage(data.offset + data.limit)}>下一页</button></div>
    </>}
  </div>
}
