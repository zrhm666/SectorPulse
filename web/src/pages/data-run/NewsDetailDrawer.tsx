import type { DataRunNewsDetailView } from '../../dataRunsApi'
import WorkbenchDrawer from './WorkbenchDrawer'

const LABELS = { FULL_TEXT: '全文', SUMMARY: '摘要', FLASH: '快讯', LINK_ONLY: '仅链接' } as const

export default function NewsDetailDrawer({ detail, loading, error, onClose }: {
  detail: DataRunNewsDetailView | null
  loading: boolean
  error: string | null
  onClose: () => void
}) {
  const title = detail?.title || '新闻详情'
  return <WorkbenchDrawer title={title} onClose={onClose}>
    {loading && <p className="status-detail">正在加载已保存新闻详情…</p>}
    {error && <p className="panel-error" role="alert">{error}</p>}
    {detail && <>
      <section className="drawer-section"><div className="news-detail-heading"><span className="content-kind-badge" data-kind={detail.content_kind}>{LABELS[detail.content_kind]}</span><span>{detail.publisher ?? detail.source_id} · {detail.source_grade}</span></div>
        {detail.content_available ? <p className="news-detail-content">{detail.content}</p> : <p className="status-detail">该来源未提供可保存的文本内容。</p>}
        {detail.content_kind !== 'FULL_TEXT' && <p className="content-storage-notice">系统未保存新闻全文</p>}
      </section>
      <section className="drawer-section"><h3>来源与时间</h3><dl className="drawer-facts drawer-facts--stacked">
        <div><dt>文档 ID</dt><dd><code>{detail.document_id}</code></dd></div>
        <div><dt>来源</dt><dd>{detail.source_id}</dd></div>
        <div><dt>发布时间</dt><dd>{detail.published_at ? new Date(detail.published_at).toLocaleString('zh-CN') : 'Provider 未返回'}</dd></div>
        <div><dt>来源观测时间</dt><dd>{detail.source_observed_at ? new Date(detail.source_observed_at).toLocaleString('zh-CN') : 'Provider 未返回'}</dd></div>
        <div><dt>系统采集时间</dt><dd>{new Date(detail.collected_at).toLocaleString('zh-CN')}</dd></div>
      </dl></section>
      {detail.citation_url && <a className="button button-secondary drawer-source-link" href={detail.citation_url} target="_blank" rel="noreferrer">打开安全原文链接</a>}
    </>}
  </WorkbenchDrawer>
}
