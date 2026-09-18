import { useCallback, useEffect, useState } from 'react'
import InlineAlert from '../../components/ui/InlineAlert'
import LoadingState from '../../components/ui/LoadingState'
import ManagementDrawer from '../../components/ui/ManagementDrawer'
import { useFeedback } from '../../components/ui/FeedbackProvider'
import {
  archiveVersion,
  fetchDocument,
  fetchSource,
  saveSource,
  type ResearchDocumentDetail,
  type ResearchVersion,
} from '../../researchLibraryApi'
import { LibraryStatusBadge } from './DocumentTable'

// 抽屉里的三个区块各自回答一个问题："这一版能不能被检索"、"它卡在哪一步"、"谁动过它"。
// 归档按钮只出现在已发布过的版本上：一个还在处理的版本没有可归档的东西，给了按钮就等于
// 给了一个必然失败的入口。
const ARCHIVABLE = new Set(['ACTIVE', 'SUPERSEDED'])

export type DocumentDetailDrawerProps = {
  open: boolean
  documentId: string | null
  actor: string
  onClose: () => void
  onChanged: () => void
}

export default function DocumentDetailDrawer({
  open,
  documentId,
  actor,
  onClose,
  onChanged,
}: DocumentDetailDrawerProps) {
  const [detail, setDetail] = useState<ResearchDocumentDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const feedback = useFeedback()

  const load = useCallback(() => {
    if (!documentId) return () => undefined
    let active = true
    setLoading(true)
    setFailed(false)
    fetchDocument(documentId)
      .then((result) => {
        if (active) setDetail(result)
      })
      .catch(() => {
        if (active) setFailed(true)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [documentId])

  useEffect(() => {
    if (!open) {
      setDetail(null)
      return
    }
    return load()
  }, [open, load])

  const preview = async (version: ResearchVersion) => {
    setBusy(version.document_version_id)
    try {
      const source = await fetchSource(documentId ?? '', version.document_version_id)
      saveSource(source)
      feedback.success(source.filename ? `已取回原件：${source.filename}` : '已取回原件。')
    } catch {
      feedback.error('原件取回失败，请稍后重试。')
    } finally {
      setBusy(null)
    }
  }

  const archive = async (version: ResearchVersion) => {
    setBusy(version.document_version_id)
    try {
      await archiveVersion(documentId ?? '', version.document_version_id, { actor: actor.trim() })
      feedback.success(`v${version.version_number} 已归档。`)
      load()
      onChanged()
    } catch {
      feedback.error('归档没有成功，请稍后重试。')
    } finally {
      setBusy(null)
    }
  }

  const actorReady = actor.trim().length > 0

  return (
    <ManagementDrawer
      open={open}
      title={detail?.document.title ?? '资料详情'}
      description="版本、摄取任务与治理记录都来自权威库。"
      onClose={onClose}
    >
      {loading && <LoadingState label="正在加载资料详情…" />}
      {!loading && failed && (
        <InlineAlert tone="error" title="无法加载资料详情">
          <p>请确认服务可用后重试。</p>
          <button className="button button-secondary" type="button" onClick={load}>
            重新加载
          </button>
        </InlineAlert>
      )}
      {!loading && !failed && detail && (
        <>
          <section className="research-detail-section">
            <h3>版本历史</h3>
            <ol className="research-version-list">
              {detail.versions.map((version) => (
                <li key={version.document_version_id} className="research-version-list__item">
                  <div className="research-version-list__heading">
                    <strong>{`v${version.version_number}`}</strong>
                    <LibraryStatusBadge status={version.status} kind="version" />
                  </div>
                  <p className="research-version-list__meta">
                    {`上传于 ${version.uploaded_at.slice(0, 10)}`}
                    {version.expected_chunk_count !== null && ` · ${version.expected_chunk_count} 个切片`}
                  </p>
                  <div className="research-version-list__actions">
                    {version.has_source && (
                      <button
                        className="button button-secondary"
                        type="button"
                        disabled={busy === version.document_version_id}
                        onClick={() => preview(version)}
                      >
                        下载原件
                      </button>
                    )}
                    {ARCHIVABLE.has(version.status) && (
                      <button
                        className="button button-secondary"
                        type="button"
                        disabled={!actorReady || busy === version.document_version_id}
                        onClick={() => archive(version)}
                      >
                        归档此版本
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <section className="research-detail-section">
            <h3>摄取任务</h3>
            {detail.jobs.length === 0 ? (
              <p className="research-detail-section__empty">还没有摄取任务。</p>
            ) : (
              <ul className="research-audit-list">
                {detail.jobs.map((job) => (
                  <li key={job.job_id}>
                    <LibraryStatusBadge status={job.status} kind="job" />
                    <span>第 {job.attempt_id} 次尝试</span>
                    {job.failure_reason && <span className="research-audit-list__detail">{job.failure_reason}</span>}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="research-detail-section">
            <h3>治理记录</h3>
            {detail.audit.length === 0 ? (
              <p className="research-detail-section__empty">还没有治理记录。</p>
            ) : (
              <ul className="research-audit-list">
                {detail.audit.map((entry) => (
                  <li key={entry.audit_id}>
                    <strong>{entry.actor}</strong>
                    {entry.detail}
                    <small>{entry.created_at.slice(0, 10)}</small>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </ManagementDrawer>
  )
}
