import StatusBadge, { type StatusTone } from '../../components/ui/StatusBadge'
import type {
  ResearchDocument,
  ResearchDocumentListItem,
  ResearchDocumentType,
} from '../../researchLibraryApi'

// 资料库的状态码是后端契约的一部分（`PROCESSING`、`EMBEDDING`……），但它们描述的是流水线
// 在哪一步，不是给人看的字。映射写在这里、由列表和抽屉共用：两处各写一份的那天，同一份
// 资料在两个界面上会显示成两种状态。
//
// 认不出来的状态原样显示。这是刻意的：一个新加的阶段码应当是可见的，而不是被悄悄塞进
// "处理中"里，让运维以为一切正常。

const VERSION_STATUS: Record<string, { label: string; tone: StatusTone }> = {
  PROCESSING: { label: '处理中', tone: 'info' },
  ACTIVE: { label: '已发布', tone: 'success' },
  SUPERSEDED: { label: '已被新版本替代', tone: 'neutral' },
  ARCHIVED: { label: '已归档', tone: 'neutral' },
  FAILED: { label: '处理失败', tone: 'danger' },
  DELETED: { label: '已删除', tone: 'neutral' },
  PURGED: { label: '已清理', tone: 'neutral' },
}

const JOB_STATUS: Record<string, { label: string; tone: StatusTone }> = {
  RECEIVED: { label: '已接收', tone: 'info' },
  VALIDATING: { label: '校验中', tone: 'info' },
  PARSING: { label: '解析中', tone: 'info' },
  NORMALIZING: { label: '规范化中', tone: 'info' },
  CHUNKING: { label: '切片中', tone: 'info' },
  EMBEDDING: { label: '向量化中', tone: 'info' },
  INDEXING: { label: '写入索引中', tone: 'info' },
  VERIFYING: { label: '校验索引中', tone: 'info' },
  PUBLISHED: { label: '已发布', tone: 'success' },
  RETRYABLE_FAILED: { label: '失败（可重试）', tone: 'warning' },
  PERMANENT_FAILED: { label: '失败（需人工处理）', tone: 'danger' },
  CANCELLED: { label: '已取消', tone: 'neutral' },
}

export const DOCUMENT_TYPE_LABELS: Record<ResearchDocumentType, string> = {
  report: '研究报告',
  historical_article: '历史文章',
  announcement: '公告',
  other: '其他',
}

export function versionStatusLabel(status: string): { label: string; tone: StatusTone } {
  return VERSION_STATUS[status] ?? { label: status, tone: 'neutral' }
}

export function jobStatusLabel(status: string): { label: string; tone: StatusTone } {
  return JOB_STATUS[status] ?? { label: status, tone: 'neutral' }
}

export function LibraryStatusBadge({
  status,
  kind,
}: {
  status: string
  kind: 'version' | 'job' | 'document'
}) {
  const detail = kind === 'job' ? jobStatusLabel(status) : versionStatusLabel(status)
  return <StatusBadge status={status} label={detail.label} tone={detail.tone} />
}

/** 列出"这份资料现在处于什么状态"：删除 > 摄取任务 > 当前版本。 */
function rowStatus(item: ResearchDocumentListItem): { status: string; kind: 'version' | 'job' | 'document' } {
  const { document, latest_job: job, versions } = item
  if (document.deleted_at) return { status: 'DELETED', kind: 'document' }
  if (job) return { status: job.status, kind: 'job' }
  const current = versions.find((version) => version.document_version_id === document.current_version_id)
  return current ? { status: current.status, kind: 'version' } : { status: '尚未上传版本', kind: 'document' }
}

export type DocumentTableProps = {
  items: ResearchDocumentListItem[]
  actorReady: boolean
  onOpen: (documentId: string) => void
  onDelete: (document: ResearchDocument) => void
  onRestore: (document: ResearchDocument) => void
}

export default function DocumentTable({ items, actorReady, onOpen, onDelete, onRestore }: DocumentTableProps) {
  return (
    <div className="run-table-wrap">
      <table className="run-table research-document-table" aria-label="内部资料">
        <thead>
          <tr>
            <th>资料</th>
            <th>类型</th>
            <th>当前版本</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const { document, versions } = item
            const current = versions.find((version) => version.document_version_id === document.current_version_id)
            const state = rowStatus(item)
            return (
              <tr key={document.document_id}>
                <td data-label="资料">
                  <strong>{document.title}</strong>
                  <small className="research-document-table__meta">
                    {[document.institution, document.author].filter(Boolean).join(' · ') || '未记录来源'}
                    <span> 来源权重 {document.source_weight}</span>
                  </small>
                </td>
                <td data-label="类型">{DOCUMENT_TYPE_LABELS[document.document_type] ?? document.document_type}</td>
                <td data-label="当前版本">{current ? `v${current.version_number}` : '—'}</td>
                <td data-label="状态">
                  <LibraryStatusBadge status={state.status} kind={state.kind} />
                  {document.deleted_at && document.purge_after && (
                    <small className="research-document-table__meta">保留至 {document.purge_after.slice(0, 10)}</small>
                  )}
                </td>
                <td data-label="操作">
                  <div className="research-document-table__actions">
                    <button className="button button-secondary" type="button" onClick={() => onOpen(document.document_id)}>
                      查看详情
                    </button>
                    {document.deleted_at ? (
                      <button
                        className="button button-secondary"
                        type="button"
                        disabled={!actorReady}
                        onClick={() => onRestore(document)}
                      >
                        恢复资料
                      </button>
                    ) : (
                      <button
                        className="button button-secondary"
                        type="button"
                        disabled={!actorReady}
                        onClick={() => onDelete(document)}
                      >
                        删除资料
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

