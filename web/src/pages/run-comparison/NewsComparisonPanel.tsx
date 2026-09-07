import { useCallback, useState } from 'react'
import LoadingState from '../../components/ui/LoadingState'
import Panel from '../../components/ui/Panel'
import type { ComparisonPair, NewsComparisonPage } from '../../runComparisonsApi'
import { fetchComparisonNews, type MembershipFilter } from '../../runComparisonsApi'
import useComparisonRequest from '../../hooks/useComparisonRequest'
import { ComparisonPagination, membershipLabel, QueryError } from './ComparisonShared'

export default function NewsComparisonPanel({ pair }: { pair: ComparisonPair }) {
  const [membership, setMembership] = useState<MembershipFilter>('ALL')
  const [offset, setOffset] = useState(0)
  const load = useCallback((signal: AbortSignal) => fetchComparisonNews(pair, { membership, offset, limit: 20 }, signal), [pair, membership, offset])
  const query = useComparisonRequest(JSON.stringify([pair, membership, offset]), load)
  const data = query.data as NewsComparisonPage | null
  return <Panel title="新闻记录" description="比较每次运行实际留存的新闻成员；文字是当前保存的元数据，不是历史正文快照。" density="compact">
    <div className="comparison-panel-toolbar"><label>新闻成员关系<select aria-label="新闻成员关系" value={membership} onChange={(event) => { setMembership(event.target.value as MembershipFilter); setOffset(0) }}><option value="ALL">全部</option><option value="BOTH">两次均留存</option><option value="ONLY_BASE">仅基准留存</option><option value="ONLY_COMPARE">仅对照留存</option></select></label></div>
    {query.loading && <LoadingState label="正在加载新闻记录…" />}{query.error && <QueryError title="新闻记录读取失败" error={query.error} retry={query.reload} />}
    {data && (
      !data.available ? (
        <div className="comparison-empty"><h3>新闻差异无法核验</h3><p>至少一侧未留存可核验的成员记录，不能视为零条新闻。基准 A：{data.base_news.recorded_count ? `${data.base_news.recorded_count} 条成员记录` : '未留存成员记录'}；对照 B：{data.compare_news.recorded_count ? `${data.compare_news.recorded_count} 条成员记录` : '未留存成员记录'}。</p></div>
      ) : (
        <>
          <div className="comparison-news-counts">{data.counts && <span>两次均留存 {data.counts.both} · 仅基准留存 {data.counts.only_base} · 仅对照留存 {data.counts.only_compare}</span>}<strong>共 {data.total} 条</strong></div>
          <ul className="comparison-news-list">{data.items.map((item) => <NewsItem key={item.document_id} item={item} />)}</ul>
          <ComparisonPagination offset={data.offset} limit={data.limit} total={data.total ?? 0} busy={query.loading} onPage={setOffset} />
        </>
      )
    )}
  </Panel>
}
function NewsItem({ item }: { item: NewsComparisonPage['items'][number] }) {
  const [open, setOpen] = useState(false)
  const meta = item.metadata
  return <li className="comparison-news-item"><div className="comparison-news-item__header"><div><strong>{meta?.title ?? item.document_id}</strong><span className="comparison-membership">{membershipLabel[item.membership]}</span></div><button type="button" className="comparison-details-button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? '收起摘要' : '查看摘要'}</button></div>{meta ? <><p className="comparison-news-item__meta">{meta.source_id}{meta.publisher ? ` · ${meta.publisher}` : ''} · 当前保存的新闻元数据，非历史正文快照</p>{open && <p className="comparison-news-item__summary">{meta.summary ?? '暂无摘要'}</p>}{meta.citation_url && /^https?:\/\//i.test(meta.citation_url) && <a href={meta.citation_url} target="_blank" rel="noopener noreferrer">查看原文</a>}</> : <p className="comparison-news-item__meta">新闻元数据不可用 · ID：{item.document_id}</p>}</li>
}
