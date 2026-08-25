import type { DataRunNewsRecordsView, DataStatus } from '../../dataRunsApi'

const STATUSES: DataStatus[] = ['SUCCESS', 'EMPTY', 'PARTIAL', 'STALE', 'UNAVAILABLE', 'FAILED']

export default function NewsRecordsPanel({ data, loading, error, sourceId, status, sourceOptions, onSourceChange, onStatusChange, onPage }: {
  data: DataRunNewsRecordsView | null
  loading: boolean
  error: string | null
  sourceId: string
  status: '' | DataStatus
  sourceOptions: string[]
  onSourceChange: (value: string) => void
  onStatusChange: (value: '' | DataStatus) => void
  onPage: (offset: number) => void
}) {
  return <div>
    <section className="news-record-toolbar" aria-label="新闻筛选">
      <label>来源<select value={sourceId} onChange={(event) => onSourceChange(event.target.value)}><option value="">全部来源</option>{sourceOptions.map((source) => <option key={source} value={source}>{source}</option>)}</select></label>
      <label>查询状态<select value={status} onChange={(event) => onStatusChange(event.target.value as '' | DataStatus)}><option value="">全部状态</option>{STATUSES.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
    </section>
    {loading && <p className="status-detail">正在加载 Provider 新闻记录…</p>}
    {error && <p className="panel-error" role="alert">{error}</p>}
    {!loading && data?.coverage_notice && <p className="coverage-notice">{data.coverage_notice}</p>}
    {!loading && !error && (!data || data.items.length === 0) && <p className="status-detail">当前筛选条件下没有新闻记录。</p>}
    {!loading && data && data.items.length > 0 && <>
      <div className="news-record-list">{data.items.map((item) => <article key={item.document_id}>
        <header><div><h3>{item.title || '无标题新闻'}</h3><p>{item.publisher ?? item.source_id} · {item.source_grade}</p></div><span data-status={item.query_status ?? undefined}>{item.query_status ?? '历史记录'}</span></header>
        <p>{item.summary ?? '该来源未提供摘要。'}</p>
        <dl><div><dt>Provider</dt><dd>{item.query_source_id}</dd></div><div><dt>发布时间</dt><dd>{item.published_at ? new Date(item.published_at).toLocaleString('zh-CN') : '未返回'}</dd></div><div><dt>采集时间</dt><dd>{new Date(item.collected_at).toLocaleString('zh-CN')}</dd></div><div><dt>查询</dt><dd>{item.query_type ?? '历史记录'} · {item.query_ids.length ? item.query_ids.join('、') : '未保存'}</dd></div></dl>
        {item.citation_url && <a href={item.citation_url} target="_blank" rel="noreferrer">查看原文</a>}
      </article>)}</div>
      <div className="pagination"><button className="button button-secondary" type="button" disabled={data.offset === 0} onClick={() => onPage(Math.max(0, data.offset - data.limit))}>上一页</button><span>{data.offset + 1}–{Math.min(data.offset + data.limit, data.total)} / {data.total}</span><button className="button button-secondary" type="button" disabled={data.offset + data.limit >= data.total} onClick={() => onPage(data.offset + data.limit)}>下一页</button></div>
    </>}
  </div>
}
