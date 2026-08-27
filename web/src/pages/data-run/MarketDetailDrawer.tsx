import type { MarketSectorView, MarketSnapshotSummary } from '../../dataRunsApi'
import WorkbenchDrawer from './WorkbenchDrawer'

function value(available: boolean | undefined, content: string | number | null, suffix = '') {
  return available === false || content == null ? 'Provider 未返回' : `${content}${suffix}`
}

export default function MarketDetailDrawer({ item, snapshot, onClose }: {
  item: MarketSectorView
  snapshot: MarketSnapshotSummary | null
  onClose: () => void
}) {
  const fields = item.field_availability ?? {}
  return <WorkbenchDrawer title={`${item.name}行情详情`} onClose={onClose}>
    <section className="drawer-section"><h3>行情字段</h3><dl className="drawer-facts">
      <div><dt>板块代码</dt><dd>{item.sector_id}</dd></div>
      <div><dt>涨跌幅</dt><dd>{value(fields.pct_change, item.pct_change, '%')}</dd></div>
      <div><dt>换手率</dt><dd>{value(fields.turnover_rate, item.turnover_rate, '%')}</dd></div>
      <div><dt>上涨 / 下跌</dt><dd>{fields.advancers === false || fields.decliners === false ? 'Provider 未返回' : `${item.advancers} / ${item.decliners}`}</dd></div>
      <div><dt>领涨股</dt><dd>{value(fields.leader_name, item.leader_name)}</dd></div>
      <div><dt>领涨幅</dt><dd>{value(fields.leader_pct_change, item.leader_pct_change, '%')}</dd></div>
    </dl></section>
    <section className="drawer-section"><h3>采集血缘</h3>{snapshot ? <dl className="drawer-facts drawer-facts--stacked">
      <div><dt>Provider</dt><dd>{snapshot.provider_id}</dd></div>
      <div><dt>来源版本</dt><dd>{snapshot.source_version}</dd></div>
      <div><dt>分类版本</dt><dd>{snapshot.classification_version}</dd></div>
      <div><dt>观测时间</dt><dd>{new Date(snapshot.observed_at).toLocaleString('zh-CN')}</dd></div>
      <div><dt>采集时间</dt><dd>{new Date(snapshot.collected_at).toLocaleString('zh-CN')}</dd></div>
      <div><dt>原始响应摘要</dt><dd><code>{snapshot.raw_artifact_sha256 ?? '历史运行未记录'}</code></dd></div>
    </dl> : <p>当前运行未保存该板块的快照血缘。</p>}</section>
  </WorkbenchDrawer>
}
