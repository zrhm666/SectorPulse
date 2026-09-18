import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ResearchLibraryApiError,
  ResearchLibraryDisabledError,
  archiveVersion,
  fetchDocument,
  fetchDocuments,
  fetchSource,
  restoreDocument,
  saveSource,
  setSourceWeight,
  softDeleteDocument,
  uploadDocument,
} from './researchLibraryApi'

function respond(body: unknown, init: ResponseInit = { status: 200 }) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), init),
  ))
}

function lastCall() {
  const calls = vi.mocked(fetch).mock.calls
  const call = calls[calls.length - 1]
  if (!call) throw new Error('fetch 没有被调用')
  const [rawUrl, init] = call
  return { url: new URL(String(rawUrl), 'http://localhost'), init: init as RequestInit }
}

const document = {
  document_id: 'doc_1',
  title: '储能行业 2026 年中期策略',
  document_type: 'report',
  author: '韩雨',
  institution: '某研究所',
  source_weight: '0.80',
  current_version_id: 'ver_1',
  created_at: '2026-09-01T08:00:00+00:00',
  deleted_at: null,
  purge_after: null,
}

const version = {
  document_version_id: 'ver_1',
  version_number: 1,
  status: 'ACTIVE',
  uploaded_at: '2026-09-01T08:00:00+00:00',
  published_at: '2026-09-01T08:05:00+00:00',
  effective_from: null,
  effective_to: null,
  indexed_at: '2026-09-01T08:05:00+00:00',
  expected_chunk_count: 12,
  has_source: true,
}

const job = {
  job_id: 'job_1',
  document_version_id: 'ver_1',
  status: 'PUBLISHED',
  attempt_id: 1,
  max_attempts: 3,
  failure_reason: null,
  updated_at: '2026-09-01T08:05:00+00:00',
}

describe('researchLibraryApi', () => {
  afterEach(() => vi.restoreAllMocks())

  it('loads the document list the page shows', async () => {
    respond({ corpus_generation: 'gen_1', documents: [{ document, versions: [version], latest_job: job }] })

    const result = await fetchDocuments()

    const { url, init } = lastCall()
    expect(url.pathname).toBe('/api/research-library/documents')
    expect(url.searchParams.get('include_deleted')).toBeNull()
    expect(init.method ?? 'GET').toBe('GET')
    expect(result.documents).toHaveLength(1)
    expect(result.documents[0].document.title).toBe('储能行业 2026 年中期策略')
  })

  it('can ask for deleted documents so they stay restorable', async () => {
    respond({ corpus_generation: 'gen_1', documents: [] })

    await fetchDocuments({ includeDeleted: true })

    expect(lastCall().url.searchParams.get('include_deleted')).toBe('true')
  })

  it('loads one document with its versions, jobs and audit trail', async () => {
    respond({
      document,
      versions: [version],
      jobs: [job],
      audit: [
        {
          audit_id: 'audit_1',
          document_id: 'doc_1',
          document_version_id: 'ver_1',
          action: 'register_version',
          actor: '韩雨',
          detail: '登记了第 1 版',
          created_at: '2026-09-01T08:00:00+00:00',
        },
      ],
    })

    const detail = await fetchDocument('doc_1')

    expect(lastCall().url.pathname).toBe('/api/research-library/documents/doc_1')
    expect(detail.versions[0].version_number).toBe(1)
    expect(detail.audit[0].actor).toBe('韩雨')
  })

  it('uploads a file as the raw request body and names the uploader in the query', async () => {
    respond({ document, version, job, created: true, scan_status: 'clean', scan_detail: null }, { status: 201 })
    const file = new File(['储能'], '储能报告.txt', { type: 'text/plain' })

    const result = await uploadDocument({
      file,
      target: 'new_document',
      actor: '韩雨',
      title: '储能行业 2026 年中期策略',
      documentType: 'report',
    })

    const { url, init } = lastCall()
    expect(url.pathname).toBe('/api/research-library/uploads')
    expect(url.searchParams.get('target')).toBe('new_document')
    expect(url.searchParams.get('actor')).toBe('韩雨')
    expect(url.searchParams.get('title')).toBe('储能行业 2026 年中期策略')
    expect(url.searchParams.get('document_type')).toBe('report')
    expect(init.method).toBe('POST')
    expect(init.body).toBe(file)
    expect(new Headers(init.headers).get('Content-Type')).toBe('text/plain')
    // 头只能放 latin-1：中文名必须转义，否则 fetch 直接抛 TypeError。
    expect(new Headers(init.headers).get('X-Research-Filename')).toBe(
      encodeURIComponent('储能报告.txt'),
    )
    expect(result.created).toBe(true)
  })

  it('uploads a new version of a named document', async () => {
    respond({ document, version, job, created: true }, { status: 201 })
    const file = new File(['储能'], '修订版.txt', { type: 'text/plain' })

    await uploadDocument({ file, target: 'new_version', documentId: 'doc_1', actor: '韩雨' })

    const { url } = lastCall()
    expect(url.searchParams.get('target')).toBe('new_version')
    expect(url.searchParams.get('document_id')).toBe('doc_1')
    expect(url.searchParams.get('title')).toBeNull()
  })

  it('reports an idempotent replay instead of failing it', async () => {
    respond({ document, version, job, created: false, scan_detail: '这份上传已经登记过了' }, { status: 200 })

    const result = await uploadDocument({
      file: new File(['储能'], '储能报告.txt', { type: 'text/plain' }),
      target: 'new_document',
      actor: '韩雨',
    })

    expect(result.created).toBe(false)
    expect(result.scan_detail).toBe('这份上传已经登记过了')
  })

  it('sends governance actions with the named actor', async () => {
    respond({ ...document, source_weight: '0.30' })
    await setSourceWeight('doc_1', { sourceWeight: '0.30', actor: '韩雨' })
    let call = lastCall()
    expect(call.url.pathname).toBe('/api/research-library/documents/doc_1/source-weight')
    expect(call.init.method).toBe('PATCH')
    expect(JSON.parse(String(call.init.body))).toEqual({ source_weight: '0.30', actor: '韩雨' })

    respond(version)
    await archiveVersion('doc_1', 'ver_1', { actor: '韩雨' })
    call = lastCall()
    expect(call.url.pathname).toBe('/api/research-library/documents/doc_1/versions/ver_1/archive')
    expect(JSON.parse(String(call.init.body))).toEqual({ actor: '韩雨' })

    respond({ document: { ...document, deleted_at: '2026-09-10T00:00:00+00:00' } })
    await softDeleteDocument('doc_1', '韩雨')
    call = lastCall()
    expect(call.url.pathname).toBe('/api/research-library/documents/doc_1')
    expect(call.init.method).toBe('DELETE')
    expect(call.url.searchParams.get('actor')).toBe('韩雨')

    respond(document)
    await restoreDocument('doc_1', { actor: '韩雨' })
    call = lastCall()
    expect(call.url.pathname).toBe('/api/research-library/documents/doc_1/restore')
    expect(JSON.parse(String(call.init.body))).toEqual({ actor: '韩雨' })
  })

  it('streams the original file and decodes the filename header', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response('储能原文', {
        status: 200,
        headers: {
          'Content-Type': 'text/plain',
          'X-Research-Sha256': 'a'.repeat(64),
          'X-Research-Filename': encodeURIComponent('储能报告.txt'),
        },
      }),
    ))

    const source = await fetchSource('doc_1', 'ver_1')

    expect(lastCall().url.pathname).toBe('/api/research-library/documents/doc_1/versions/ver_1/source')
    expect(source.filename).toBe('储能报告.txt')
    expect(source.contentType).toBe('text/plain')
    expect(await source.blob.text()).toBe('储能原文')
  })

  it('tells an unconfigured deployment apart from a failing one', async () => {
    respond(
      { error: { code: 'RESEARCH_LIBRARY_DISABLED', message: 'RESEARCH_LIBRARY_DISABLED', retryable: false } },
      { status: 404 },
    )

    await expect(fetchDocuments()).rejects.toBeInstanceOf(ResearchLibraryDisabledError)
  })

  it('carries the public error code for every other failure', async () => {
    respond(
      { error: { code: 'UPLOAD_TOO_LARGE', message: '文件过大', retryable: false } },
      { status: 413 },
    )

    const error = await fetchDocuments().catch((raised: unknown) => raised)

    expect(error).toBeInstanceOf(ResearchLibraryApiError)
    expect((error as ResearchLibraryApiError).code).toBe('UPLOAD_TOO_LARGE')
    expect((error as ResearchLibraryApiError).status).toBe(413)
  })

  it('survives an error response whose body is not the documented envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>502</html>', { status: 502 })))

    const error = await fetchDocuments().catch((raised: unknown) => raised)

    expect(error).toBeInstanceOf(ResearchLibraryApiError)
    expect((error as ResearchLibraryApiError).code).toBe('REQUEST_FAILED')
  })
})

describe('saveSource', () => {
  it('revokes the object URL only after the browser has had a turn to read it', () => {
    const revoked: string[] = []
    const target = URL as unknown as {
      createObjectURL?: (blob: Blob) => string
      revokeObjectURL?: (href: string) => void
    }
    // 存下来再改回去：Node 自带 `createObjectURL`，`delete` 删不掉它（不是可配置属性），
    // 于是"浏览器没有这个能力"那一支只能靠赋成非函数来构造。
    const original = { create: target.createObjectURL, revoke: target.revokeObjectURL }
    target.createObjectURL = () => 'blob:research/1'
    target.revokeObjectURL = (href) => revoked.push(href)
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    vi.useFakeTimers()

    try {
      saveSource({ blob: new Blob(['x']), filename: '报告.txt', contentType: 'text/plain' })

      // `click()` 只是把下载排进队列，浏览器读这个 URL 是之后的事。同一轮里就撤销，等于在
      // 用户唯一还在等的那件事上抢跑——而这里正是问它"有没有抢跑"的地方。
      expect(revoked).toEqual([])
      expect(click).toHaveBeenCalledTimes(1)

      vi.runAllTimers()
      expect(revoked).toEqual(['blob:research/1'])
    } finally {
      click.mockRestore()
      vi.useRealTimers()
      target.createObjectURL = original.create
      target.revokeObjectURL = original.revoke
    }
  })

  it('does nothing where the browser has no object URL support', () => {
    const target = URL as unknown as { createObjectURL?: unknown }
    const original = target.createObjectURL
    target.createObjectURL = undefined
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    try {
      saveSource({ blob: new Blob(['x']), filename: null, contentType: 'text/plain' })
      expect(click).not.toHaveBeenCalled()
    } finally {
      target.createObjectURL = original
      click.mockRestore()
    }
  })
})
