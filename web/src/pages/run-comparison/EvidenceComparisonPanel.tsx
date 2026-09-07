import { useCallback, useState } from 'react'
import LoadingState from '../../components/ui/LoadingState'
import Panel from '../../components/ui/Panel'
import type { ComparisonPair, EvidenceComparisonPage } from '../../runComparisonsApi'
import { fetchComparisonEvidence } from '../../runComparisonsApi'
import useComparisonRequest from '../../hooks/useComparisonRequest'
import { ComparisonPagination, kindLabel, membershipLabel, QueryError } from './ComparisonShared'

export default function EvidenceComparisonPanel({ pair }: { pair: ComparisonPair }) {
  const [offset, setOffset] = useState(0)
  const load = useCallback((signal: AbortSignal) => fetchComparisonEvidence(pair, { offset, limit: 20 }, signal), [pair, offset])
  const query = useComparisonRequest(JSON.stringify([pair, offset]), load)
  const data = query.data as EvidenceComparisonPage | null
  return <Panel title="板块证据" description="展示两次运行保存的板块—事件关系和原始映射说明，不推断因果。" density="compact">
    {query.loading && <LoadingState label="正在加载证据关系…" />}
    {query.error && <QueryError title="证据关系读取失败" error={query.error} retry={query.reload} />}
    {data && <>
      {data.unavailable_kinds.length > 0 && <p className="comparison-note">不可比类别：{data.unavailable_kinds.map((kind) => kindLabel[kind]).join('、')}</p>}
      {data.items.length === 0 ? <p className="comparison-empty">没有留存关联。没有关联不代表现实中没有证据。</p> : <>
        <ul className="comparison-evidence-list">{data.items.map((item) => <li key={`${item.kind}-${item.sector_id}-${item.event_id}`}>
          <header><strong>{kindLabel[item.kind]} · {item.sector_id}</strong><span>{membershipLabel[item.membership]}</span></header>
          <p>事件：{item.current_event_title ?? '事件元数据不可用'}</p>
          <dl><dt>基准 A</dt><dd>{item.base ? <>{item.base.relation_type} · {item.base.mapping_confidence} · {item.base.mapping_reason}<small>规则版本：{item.base.rule_version || '未保存'}</small></> : '无留存关联'}</dd><dt>对照 B</dt><dd>{item.compare ? <>{item.compare.relation_type} · {item.compare.mapping_confidence} · {item.compare.mapping_reason}<small>规则版本：{item.compare.rule_version || '未保存'}</small></> : '无留存关联'}</dd></dl>
        </li>)}</ul>
        <ComparisonPagination offset={data.offset} limit={data.limit} total={data.total} busy={query.loading} onPage={setOffset} />
      </>}
    </>}
  </Panel>
}
