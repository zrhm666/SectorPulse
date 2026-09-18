import { useState } from 'react'
import InlineAlert from '../../components/ui/InlineAlert'
import {
  ResearchLibraryApiError,
  ResearchLibraryDisabledError,
  uploadDocument,
  type ResearchDocumentListItem,
  type ResearchDocumentType,
  type UploadTarget,
} from '../../researchLibraryApi'
import { DOCUMENT_TYPE_LABELS } from './DocumentTable'

// 公开错误码 → 给人看的一句话。认不出来的码原样附在括号里：运维要能拿它去查日志，而一句
// "上传失败"会把唯一能指向真实原因的线索抹掉。
const UPLOAD_FAILURES: Record<string, string> = {
  UPLOAD_EMPTY: '这份文件是空的。',
  UPLOAD_TOO_LARGE: '这份文件超过了允许的大小。',
  UPLOAD_UNSUPPORTED_TYPE: '这个文件类型不受支持。',
  UPLOAD_TYPE_MISMATCH: '文件内容与声明的类型不一致。',
  INVALID_REQUEST: '上传信息不完整或格式不对。',
  RESEARCH_LIBRARY_DISABLED: '这个部署没有启用内部资料库。',
}

function uploadFailureMessage(error: unknown): string {
  if (error instanceof ResearchLibraryApiError) {
    return `${UPLOAD_FAILURES[error.code] ?? '上传没有成功。'}（${error.code}）`
  }
  if (error instanceof ResearchLibraryDisabledError) {
    return `${UPLOAD_FAILURES.RESEARCH_LIBRARY_DISABLED}（RESEARCH_LIBRARY_DISABLED）`
  }
  return '上传没有成功，请稍后重试。'
}

export type DocumentUploadPanelProps = {
  items: ResearchDocumentListItem[]
  actor: string
  onUploaded: () => void
  onCancel: () => void
}

export default function DocumentUploadPanel({ items, actor, onUploaded, onCancel }: DocumentUploadPanelProps) {
  const [target, setTarget] = useState<UploadTarget>('new_document')
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [documentType, setDocumentType] = useState<ResearchDocumentType>('report')
  const [author, setAuthor] = useState('')
  const [institution, setInstitution] = useState('')
  const [documentId, setDocumentId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const canSubmit =
    !submitting &&
    file !== null &&
    actor.trim().length > 0 &&
    (target === 'new_document' ? title.trim().length > 0 : documentId.length > 0)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!file || !canSubmit) return
    setSubmitting(true)
    setFailure(null)
    try {
      await uploadDocument({
        file,
        target,
        actor: actor.trim(),
        documentId: target === 'new_version' ? documentId : undefined,
        title: target === 'new_document' ? title.trim() : undefined,
        documentType: target === 'new_document' ? documentType : undefined,
        author: target === 'new_document' ? author.trim() || undefined : undefined,
        institution: target === 'new_document' ? institution.trim() || undefined : undefined,
      })
      onUploaded()
    } catch (error) {
      setFailure(uploadFailureMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="research-upload-form" onSubmit={submit}>
      <label>
        上传目标
        <select
          value={target}
          onChange={(event) => setTarget(event.target.value as UploadTarget)}
        >
          <option value="new_document">新资料</option>
          <option value="new_version">现有资料的新版本</option>
        </select>
      </label>

      {target === 'new_version' && (
        <label>
          选择资料
          <select required value={documentId} onChange={(event) => setDocumentId(event.target.value)}>
            <option value="">请选择…</option>
            {items
              .filter((item) => item.document.deleted_at === null)
              .map((item) => (
                <option key={item.document.document_id} value={item.document.document_id}>
                  {item.document.title}
                </option>
              ))}
          </select>
        </label>
      )}

      {target === 'new_document' && (
        <>
          <label>
            资料标题
            <input required maxLength={300} value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label>
            资料类型
            <select value={documentType} onChange={(event) => setDocumentType(event.target.value as ResearchDocumentType)}>
              {Object.entries(DOCUMENT_TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            作者
            <input maxLength={200} value={author} onChange={(event) => setAuthor(event.target.value)} />
          </label>
          <label>
            机构
            <input maxLength={200} value={institution} onChange={(event) => setInstitution(event.target.value)} />
          </label>
        </>
      )}

      <label>
        文件
        {/* 刻意不写 `required`：真正的闸门是下面那个被禁用的提交按钮，它读的是同一份状态。
            而 `required` 在文件输入上只在"状态与 DOM 不一致"时才可能生效，那种情况构造不出来。 */}
        <input type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
      </label>

      {failure && (
        <InlineAlert tone="error" title="上传失败">
          <p>{failure}</p>
        </InlineAlert>
      )}

      {actor.trim().length === 0 && <p className="research-upload-form__hint">请先填写执行人：上传是一次署名动作。</p>}

      <div className="research-upload-form__actions">
        <button className="button button-secondary" type="button" onClick={onCancel}>
          取消
        </button>
        <button className="button button-primary" type="submit" disabled={!canSubmit}>
          {submitting ? '正在上传…' : '开始上传'}
        </button>
      </div>
    </form>
  )
}
