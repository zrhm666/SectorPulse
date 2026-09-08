import type { DataRunAcquisitionView, MarketSnapshotSummary } from '../../dataRunsApi'
import { marketCapability } from './marketCapability'
import StatusBadge from '../../components/ui/StatusBadge'

const FIELD_LABELS: Record<string, string> = {
  sector_id: '板块代码', provider_sector_id: '板块代码', name: '板块名称', pct_change: '涨跌幅',
  turnover_rate: '换手率', total_market_cap: '总市值', advancers: '上涨家数',
  decliners: '下跌家数', leader_name: '领涨股',
  leader_pct_change: '领涨幅', breadth_ratio: '市场宽度',
}

function sourceFields(source: MarketSnapshotSummary) {
  const fields = source.available_fields ?? []
  return fields.length ? fields.map((field) => FIELD_LABELS[field] ?? field).join('、') : '历史记录未保存字段覆盖信息'
}

export default function AcquisitionSummary({ data, loading, error }: {
  data: DataRunAcquisitionView | null
  loading: boolean
  error: string | null
}) {
  return <section className="acquisition-summary" aria-labelledby="acquisition-title">
    <div className="acquisition-summary__heading">
      <div><h2 id="acquisition-title">本次实际获取</h2><p>这里展示数据源实际返回并已落库的数据，不代表全部字段都由来源提供。</p></div>
      {data && <span className="coverage-badge">{data.coverage === 'COMPLETE' ? '完整采集链路' : '历史关联数据'}</span>}
    </div>
    {loading && <p className="status-detail">正在读取采集记录…</p>}
    {error && <p className="panel-error" role="alert">采集摘要加载失败：{error}</p>}
    {data && <>
      {data.coverage_notice && <p className="coverage-notice">{data.coverage_notice}</p>}
      <div className="acquisition-counts">
        <div><span>数据源返回</span><strong>{data.counts.provider_results}</strong><small>所有新闻查询返回条数</small></div>
        <div><span>规范化保存</span><strong>{data.counts.normalized_documents}</strong><small>去重后落库新闻数</small></div>
        <div><span>进入证据链</span><strong>{data.counts.evidence_events}</strong><small>合并后的新闻事件数</small></div>
      </div>
      <div className="acquisition-source-grid">
        {data.market_sources.map((source) => {
          const capability = marketCapability(source)
          return <article key={`${source.kind}-${source.provider_id}`}>
            <header><strong>{source.provider_id}</strong><span>{source.kind === 'INDUSTRY' ? '行业' : '概念'} · {source.sector_count} 条</span></header>
            <p><span className="market-capability-badge" data-capability={capability.level}>{capability.label}</span></p>
            {capability.notice && <p>{capability.notice}</p>}
            <p>实际字段：{sourceFields(source)}</p>
            <small>采集 {new Date(source.collected_at).toLocaleString('zh-CN')} · 版本 {source.source_version}</small>
            {source.raw_artifact_sha256 && <code title={source.raw_artifact_sha256}>原始响应 {source.raw_artifact_sha256.slice(0, 12)}…</code>}
          </article>
        })}
        {data.news_sources.map((source) => <article key={source.source_id}>
          <header><strong>{source.source_id}</strong><StatusBadge status={source.status} /></header>
          <p>{source.query_count} 次查询 · 返回 {source.result_count} 条 · 重试 {source.retry_count} 次</p>
          <small>{source.duration_ms == null ? '耗时未记录' : `耗时 ${source.duration_ms} ms`} · 调用 {source.call_count} 次</small>
          {source.error_codes.length > 0 && <code>错误：{source.error_codes.join('、')}</code>}
        </article>)}
      </div>
      {data.market_sources.length === 0 && data.news_sources.length === 0 && <p className="status-detail">当前运行尚无可展示的 Provider 采集记录。</p>}
    </>}
  </section>
}
