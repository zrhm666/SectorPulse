// 内部研究资料库的管理 API（后端规格 18.1～18.3）。
//
// 两条贯穿这个文件的规则：
//
// 1. **浏览器拿不到模型与存储的实现标识**。返回类型里没有 `index_generation`、`object_key`
//    或 provider/model 名，因为后端根本不发这些字段——前端能显示的每一项都在这里找得到
//    出处，找不到的那些也正是它不该知道的东西。
// 2. **"这个部署没有资料库"和"资料库出故障了"是两件事**。前者是 404
//    `RESEARCH_LIBRARY_DISABLED`，页面据此显示空态；后者是可重试的错误。两者混在一起，
//    运维会去修一台本来就好好的服务器。

const BASE = '/api/research-library'

export type ResearchDocumentType = 'report' | 'historical_article' | 'announcement' | 'other'

/** 规格 7.1：用户明确选择新文档还是既有文档的新版本，没有第三种。 */
export type UploadTarget = 'new_document' | 'new_version'

export type ResearchDocument = {
  document_id: string
  title: string
  document_type: ResearchDocumentType
  author: string | null
  institution: string | null
  source_weight: string
  current_version_id: string | null
  created_at: string
  deleted_at: string | null
  purge_after: string | null
}

export type ResearchVersion = {
  document_version_id: string
  version_number: number
  status: string
  uploaded_at: string
  published_at: string | null
  effective_from: string | null
  effective_to: string | null
  indexed_at: string | null
  expected_chunk_count: number | null
  has_source: boolean
}

export type ResearchIngestionJob = {
  job_id: string
  document_version_id: string
  status: string
  attempt_id: number
  max_attempts: number
  failure_reason: string | null
  updated_at: string
}

export type ResearchAuditEntry = {
  audit_id: string
  document_id: string
  document_version_id: string | null
  action: string
  actor: string
  detail: string
  created_at: string
}

export type ResearchDocumentListItem = {
  document: ResearchDocument
  versions: ResearchVersion[]
  latest_job: ResearchIngestionJob | null
}

export type ResearchDocumentList = {
  corpus_generation: string
  documents: ResearchDocumentListItem[]
}

export type ResearchDocumentDetail = {
  document: ResearchDocument
  versions: ResearchVersion[]
  jobs: ResearchIngestionJob[]
  audit: ResearchAuditEntry[]
}

export type ResearchUploadResult = {
  document: ResearchDocument
  version: ResearchVersion
  job: ResearchIngestionJob
  created: boolean
  scan_status: string | null
  scan_detail: string | null
}

export type ResearchSource = {
  blob: Blob
  filename: string | null
  contentType: string
}

/** RAG 没有打开：这个部署就是没有资料库，不是坏了。 */
export class ResearchLibraryDisabledError extends Error {
  constructor() {
    super('这个部署没有启用内部资料库')
    this.name = 'ResearchLibraryDisabledError'
  }
}

export class ResearchLibraryApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
  ) {
    super(`资料库请求失败（HTTP ${status} / ${code}）`)
    this.name = 'ResearchLibraryApiError'
  }
}

async function toError(response: Response): Promise<Error> {
  let code = 'REQUEST_FAILED'
  try {
    const body = (await response.json()) as { error?: { code?: unknown } }
    if (typeof body?.error?.code === 'string' && body.error.code) code = body.error.code
  } catch {
    // 错误体不是约定的信封（网关页面、空体）：用稳定的回退码，不把 HTML 当成错误码。
  }
  if (response.status === 404 && code === 'RESEARCH_LIBRARY_DISABLED') {
    return new ResearchLibraryDisabledError()
  }
  return new ResearchLibraryApiError(response.status, code)
}

async function request(path: string, init: RequestInit): Promise<Response> {
  const response = await fetch(`${BASE}${path}`, init)
  if (!response.ok) throw await toError(response)
  return response
}

async function readJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await request(path, init)
  return (await response.json()) as T
}

function jsonBody(payload: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }
}

export function fetchDocuments(
  options: { includeDeleted?: boolean; signal?: AbortSignal } = {},
): Promise<ResearchDocumentList> {
  const query = new URLSearchParams()
  if (options.includeDeleted) query.set('include_deleted', 'true')
  const suffix = query.size > 0 ? `?${query}` : ''
  return readJson<ResearchDocumentList>(`/documents${suffix}`, { signal: options.signal })
}

export function fetchDocument(documentId: string, signal?: AbortSignal): Promise<ResearchDocumentDetail> {
  return readJson<ResearchDocumentDetail>(`/documents/${encodeURIComponent(documentId)}`, { signal })
}

export type UploadInput = {
  file: File
  target: UploadTarget
  actor: string
  documentId?: string
  title?: string
  documentType?: ResearchDocumentType
  author?: string
  institution?: string
}

export function uploadDocument(input: UploadInput): Promise<ResearchUploadResult> {
  // 请求体是原始字节：媒体类型与文件名走请求头，其余一切走查询串。用 `File` 直接作为 body
  // 意味着浏览器流式发送它，而不是先读进内存再拼一个 multipart 信封。
  //
  // 文件名按 RFC 3986 转义：HTTP 头只能放 latin-1，`fetch` 见到非 ASCII 的头值直接抛
  // `TypeError`——一份中文名的报告连请求都发不出去。后端在路由里解码，两个方向互逆。
  const query = new URLSearchParams({ target: input.target, actor: input.actor })
  if (input.documentId) query.set('document_id', input.documentId)
  if (input.title) query.set('title', input.title)
  if (input.documentType) query.set('document_type', input.documentType)
  if (input.author) query.set('author', input.author)
  if (input.institution) query.set('institution', input.institution)
  return readJson<ResearchUploadResult>(`/uploads?${query}`, {
    method: 'POST',
    headers: {
      'Content-Type': input.file.type || 'application/octet-stream',
      'X-Research-Filename': encodeURIComponent(input.file.name),
    },
    body: input.file,
  })
}

export function setSourceWeight(
  documentId: string,
  input: { sourceWeight: string; actor: string },
): Promise<ResearchDocument> {
  return readJson<ResearchDocument>(`/documents/${encodeURIComponent(documentId)}/source-weight`, {
    ...jsonBody({ source_weight: input.sourceWeight, actor: input.actor }),
    method: 'PATCH',
  })
}

export function archiveVersion(
  documentId: string,
  documentVersionId: string,
  input: { actor: string },
): Promise<ResearchVersion> {
  return readJson<ResearchVersion>(
    `/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(documentVersionId)}/archive`,
    jsonBody({ actor: input.actor }),
  )
}

export function softDeleteDocument(documentId: string, actor: string): Promise<{ document: ResearchDocument }> {
  const query = new URLSearchParams({ actor })
  return readJson<{ document: ResearchDocument }>(
    `/documents/${encodeURIComponent(documentId)}?${query}`,
    { method: 'DELETE' },
  )
}

export function restoreDocument(documentId: string, input: { actor: string }): Promise<ResearchDocument> {
  return readJson<ResearchDocument>(
    `/documents/${encodeURIComponent(documentId)}/restore`,
    jsonBody({ actor: input.actor }),
  )
}

export function runIngestion(jobId: string, input: { workerId: string }): Promise<ResearchIngestionJob> {
  return readJson<ResearchIngestionJob>(
    `/ingestion-jobs/${encodeURIComponent(jobId)}/run`,
    jsonBody({ worker_id: input.workerId }),
  )
}

export function retryIngestion(jobId: string, input: { actor: string }): Promise<ResearchIngestionJob> {
  return readJson<ResearchIngestionJob>(
    `/ingestion-jobs/${encodeURIComponent(jobId)}/retry`,
    jsonBody({ actor: input.actor }),
  )
}

export function fetchSource(documentId: string, documentVersionId: string): Promise<ResearchSource> {
  // 原件是私人内容：后端按块流出来，不发预签名链接——链接会绕过鉴权。
  return request(
    `/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(documentVersionId)}/source`,
    {},
  ).then(async (response) => {
    const encoded = response.headers.get('X-Research-Filename')
    let filename: string | null = null
    if (encoded) {
      try {
        filename = decodeURIComponent(encoded)
      } catch {
        // 请求头被中间设备改坏了：宁可少显示一个文件名，也不让页面崩掉。
        filename = null
      }
    }
    return {
      blob: await response.blob(),
      filename,
      contentType: response.headers.get('Content-Type') ?? 'application/octet-stream',
    }
  })
}

/** 把一份原件交给浏览器下载。jsdom 里没有 `createObjectURL`，因此那里只做到取回字节为止。 */
export function saveSource(source: ResearchSource): void {
  if (typeof URL.createObjectURL !== 'function') return
  const href = URL.createObjectURL(source.blob)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = source.filename ?? 'research-source'
  anchor.click()
  // `click()` 只是把下载排进队列，浏览器读这个 blob URL 是之后的事。在同一轮里撤销它，
  // 会不会把下载掐掉取决于实现的时序——下载是用户按了按钮之后唯一还在等的事，值得让它
  // 晚一轮再回收。
  window.setTimeout(() => URL.revokeObjectURL(href), 0)
}
