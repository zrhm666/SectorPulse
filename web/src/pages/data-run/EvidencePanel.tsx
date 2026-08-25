import type { DataRunEvidenceView } from '../../dataRunsApi'

export default function EvidencePanel({ data, loading, error }: { data: DataRunEvidenceView | null; loading: boolean; error: string | null }) {
  if (loading) return <p className="status-detail">正在加载新闻证据…</p>
  if (error) return <p className="panel-error" role="alert">{error}</p>
  if (!data || data.events.length === 0) return <p className="status-detail">新闻证据尚未产生，新闻采集或证据构建可能仍在进行。</p>
  return <div className="evidence-event-list">{data.events.map((event) => <article key={event.event_id} className="evidence-event"><header><div><h3>{event.canonical_title}</h3><p>{event.first_published_at ? new Date(event.first_published_at).toLocaleString('zh-CN') : '发布时间未知'} · 去重：{event.deduplication_reason}</p></div><span>{event.sector_ids.length} 个关联板块</span></header>
    {event.links.length > 0 && <div className="evidence-mappings">{event.links.map((link) => <div key={`${link.sector_kind}-${link.sector_id}`}><strong>{link.sector_name ?? link.sector_id}（{link.sector_kind === 'INDUSTRY' ? '行业' : '概念'}）</strong><span>置信度 {link.mapping_confidence}</span><small>命中实体：{link.matched_entities?.length ? link.matched_entities.join('、') : '未记录'}</small><p>{link.mapping_reason}</p></div>)}</div>}
    {event.documents.map((document) => <section key={document.document_id}><div><strong>{document.publisher ?? document.source_id}</strong><small>{document.source_grade}</small></div><p>{document.summary ?? '该来源未提供摘要。'}</p>{document.citation_url && <a href={document.citation_url} target="_blank" rel="noreferrer">查看原文</a>}</section>)}</article>)}</div>
}
