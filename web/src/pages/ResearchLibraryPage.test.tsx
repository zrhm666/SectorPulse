import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ResearchLibraryPage from './ResearchLibraryPage'
import * as api from '../researchLibraryApi'

// 只替换网络调用，保留真实的错误类：页面靠 `instanceof` 把"没有资料库"和"资料库坏了"分开，
// 而那个判断读的是类上带的 `code` 与 `status`。一个连构造器都被替换掉的假模块会让这两条
// 路径都变成"随便什么错误"，测试也就测不到那条分支。
vi.mock('../researchLibraryApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../researchLibraryApi')>()
  return {
    ...actual,
    archiveVersion: vi.fn(),
    fetchDocument: vi.fn(),
    fetchDocuments: vi.fn(),
    fetchSource: vi.fn(),
    restoreDocument: vi.fn(),
    retryIngestion: vi.fn(),
    runIngestion: vi.fn(),
    saveSource: vi.fn(),
    setSourceWeight: vi.fn(),
    softDeleteDocument: vi.fn(),
    uploadDocument: vi.fn(),
  }
})

type Document = api.ResearchDocument
type Version = api.ResearchVersion
type Job = api.ResearchIngestionJob

function aDocument(overrides: Partial<Document> = {}): Document {
  return {
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
    ...overrides,
  }
}

function aVersion(overrides: Partial<Version> = {}): Version {
  return {
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
    ...overrides,
  }
}

function aJob(overrides: Partial<Job> = {}): Job {
  return {
    job_id: 'job_1',
    document_version_id: 'ver_1',
    status: 'PUBLISHED',
    attempt_id: 1,
    max_attempts: 3,
    failure_reason: null,
    updated_at: '2026-09-01T08:05:00+00:00',
    ...overrides,
  }
}

function listResponse(
  entries: Array<{ document: Document; versions: Version[]; latest_job: Job | null }>,
): api.ResearchDocumentList {
  return { corpus_generation: 'gen_1', documents: entries }
}

async function renderPage() {
  render(<ResearchLibraryPage />)
  await screen.findByRole('heading', { level: 2, name: '资料列表' })
}

async function nameActor(name = '韩雨') {
  await userEvent.type(screen.getByLabelText('执行人'), name)
}

describe('ResearchLibraryPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.fetchDocuments).mockResolvedValue(
      listResponse([{ document: aDocument(), versions: [aVersion()], latest_job: aJob() }]),
    )
    vi.mocked(api.fetchDocument).mockResolvedValue({
      document: aDocument(),
      versions: [aVersion()],
      jobs: [aJob()],
      audit: [],
    })
  })

  it('shows a loading state while the library is being listed', () => {
    vi.mocked(api.fetchDocuments).mockReturnValue(new Promise(() => undefined))

    render(<ResearchLibraryPage />)

    expect(screen.getByRole('status')).toHaveTextContent('正在加载资料库')
  })

  it('lists documents with their version and a readable ingestion status', async () => {
    vi.mocked(api.fetchDocuments).mockResolvedValue(
      listResponse([
        {
          document: aDocument({ document_id: 'doc_2', title: '锂电月度跟踪' }),
          versions: [aVersion({ document_version_id: 'ver_2', status: 'PROCESSING' })],
          latest_job: aJob({ document_version_id: 'ver_2', status: 'EMBEDDING' }),
        },
        { document: aDocument(), versions: [aVersion()], latest_job: aJob() },
      ]),
    )

    await renderPage()

    expect(screen.getByText('锂电月度跟踪')).toBeInTheDocument()
    expect(screen.getByText('储能行业 2026 年中期策略')).toBeInTheDocument()
    expect(screen.getByText('向量化中')).toBeInTheDocument()
    expect(screen.getByText('已发布')).toBeInTheDocument()
    expect(screen.getByText('v1')).toBeInTheDocument()
    expect(screen.queryByText('EMBEDDING')).not.toBeInTheDocument()
    expect(api.fetchDocuments).toHaveBeenCalledWith({ includeDeleted: true })
  })

  it('treats an unconfigured deployment as an empty state, not as a failure', async () => {
    vi.mocked(api.fetchDocuments).mockRejectedValue(new api.ResearchLibraryDisabledError())

    render(<ResearchLibraryPage />)

    expect(await screen.findByRole('heading', { level: 2, name: '资料库未启用' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows a retryable error when the library cannot be reached', async () => {
    vi.mocked(api.fetchDocuments)
      .mockRejectedValueOnce(new api.ResearchLibraryApiError(503, 'SERVICE_UNAVAILABLE'))
      .mockResolvedValue(listResponse([]))

    render(<ResearchLibraryPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('无法加载资料库')
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(await screen.findByRole('heading', { level: 2, name: '还没有内部资料' })).toBeInTheDocument()
  })

  it('guides the user when the library is connected but empty', async () => {
    vi.mocked(api.fetchDocuments).mockResolvedValue(listResponse([]))

    render(<ResearchLibraryPage />)

    expect(await screen.findByRole('heading', { level: 2, name: '还没有内部资料' })).toBeInTheDocument()
  })

  it('uploads a new document and refreshes the list', async () => {
    vi.mocked(api.uploadDocument).mockResolvedValue({
      document: aDocument({ document_id: 'doc_9', title: '储能月度跟踪' }),
      version: aVersion({ document_version_id: 'ver_9' }),
      job: aJob({ job_id: 'job_9' }),
      created: true,
      scan_status: 'clean',
      scan_detail: null,
    })
    await renderPage()
    await nameActor()

    await userEvent.click(screen.getByRole('button', { name: '上传资料' }))
    const panel = screen.getByRole('dialog', { name: '上传资料' })
    const file = new File(['储能'], '储能月度跟踪.txt', { type: 'text/plain' })
    await userEvent.upload(within(panel).getByLabelText('文件'), file)
    await userEvent.type(within(panel).getByLabelText('资料标题'), '储能月度跟踪')
    await userEvent.selectOptions(within(panel).getByLabelText('资料类型'), 'announcement')
    await userEvent.click(within(panel).getByRole('button', { name: '开始上传' }))

    await waitFor(() =>
      expect(api.uploadDocument).toHaveBeenCalledWith(
        expect.objectContaining({
          file,
          target: 'new_document',
          actor: '韩雨',
          title: '储能月度跟踪',
          documentType: 'announcement',
        }),
      ),
    )
    expect(screen.queryByRole('dialog', { name: '上传资料' })).not.toBeInTheDocument()
    await waitFor(() => expect(api.fetchDocuments).toHaveBeenCalledTimes(2))
  })

  it('uploads a new version of an explicitly chosen document', async () => {
    vi.mocked(api.fetchDocuments).mockResolvedValue(
      listResponse([
        { document: aDocument(), versions: [aVersion()], latest_job: aJob() },
        {
          document: aDocument({ document_id: 'doc_2', title: '锂电月度跟踪' }),
          versions: [aVersion({ document_version_id: 'ver_2' })],
          latest_job: aJob({ document_version_id: 'ver_2' }),
        },
      ]),
    )
    vi.mocked(api.uploadDocument).mockResolvedValue({
      document: aDocument({ document_id: 'doc_2', title: '锂电月度跟踪' }),
      version: aVersion({ document_version_id: 'ver_20', version_number: 2 }),
      job: aJob({ job_id: 'job_20' }),
      created: true,
      scan_status: 'clean',
      scan_detail: null,
    })
    await renderPage()
    await nameActor()

    await userEvent.click(screen.getByRole('button', { name: '上传资料' }))
    const panel = screen.getByRole('dialog', { name: '上传资料' })
    await userEvent.selectOptions(within(panel).getByLabelText('上传目标'), 'new_version')
    // 新版本的标题与类型跟着既有资料走，因此这两个字段在这一支里不该出现——否则用户会以为
    // 它们会覆盖掉那份资料的身份。
    expect(within(panel).queryByLabelText('资料标题')).toBeNull()
    const start = within(panel).getByRole('button', { name: '开始上传' })
    expect(start).toBeDisabled()

    await userEvent.selectOptions(within(panel).getByLabelText('选择资料'), 'doc_2')
    await userEvent.upload(within(panel).getByLabelText('文件'), new File(['锂电'], '锂电v2.txt', { type: 'text/plain' }))
    await userEvent.click(start)

    await waitFor(() =>
      expect(api.uploadDocument).toHaveBeenCalledWith(
        expect.objectContaining({ target: 'new_version', documentId: 'doc_2', actor: '韩雨' }),
      ),
    )
    expect(screen.queryByRole('dialog', { name: '上传资料' })).not.toBeInTheDocument()
  })

  it('shows progress while the file is still being sent', async () => {
    vi.mocked(api.uploadDocument).mockReturnValue(new Promise(() => undefined))
    await renderPage()
    await nameActor()

    await userEvent.click(screen.getByRole('button', { name: '上传资料' }))
    const panel = screen.getByRole('dialog', { name: '上传资料' })
    await userEvent.upload(within(panel).getByLabelText('文件'), new File(['储能'], '储能.txt', { type: 'text/plain' }))
    await userEvent.type(within(panel).getByLabelText('资料标题'), '储能月度跟踪')
    await userEvent.click(within(panel).getByRole('button', { name: '开始上传' }))

    const sending = await within(panel).findByRole('button', { name: '正在上传…' })
    expect(sending).toBeDisabled()
    expect(screen.getByRole('dialog', { name: '上传资料' })).toBeInTheDocument()
  })

  it('keeps the panel open and explains a refused upload', async () => {
    vi.mocked(api.uploadDocument).mockRejectedValue(
      new api.ResearchLibraryApiError(415, 'UPLOAD_UNSUPPORTED_TYPE'),
    )
    await renderPage()
    await nameActor()

    await userEvent.click(screen.getByRole('button', { name: '上传资料' }))
    const panel = screen.getByRole('dialog', { name: '上传资料' })
    await userEvent.upload(within(panel).getByLabelText('文件'), new File(['x'], 'x.exe', { type: 'application/x-msdownload' }))
    await userEvent.type(within(panel).getByLabelText('资料标题'), '一份报告')
    await userEvent.click(within(panel).getByRole('button', { name: '开始上传' }))

    const alert = await within(panel).findByRole('alert')
    expect(alert).toHaveTextContent('上传失败')
    expect(alert).toHaveTextContent('UPLOAD_UNSUPPORTED_TYPE')
    expect(screen.getByRole('dialog', { name: '上传资料' })).toBeInTheDocument()
  })

  it('opens a version history drawer with the audit trail', async () => {
    vi.mocked(api.fetchDocument).mockResolvedValue({
      document: aDocument(),
      versions: [
        aVersion({ document_version_id: 'ver_2', version_number: 2, status: 'PROCESSING' }),
        aVersion({ document_version_id: 'ver_1', version_number: 1, status: 'SUPERSEDED' }),
      ],
      jobs: [aJob({ status: 'RETRYABLE_FAILED', failure_reason: '解析服务不可用' })],
      audit: [
        {
          audit_id: 'audit_1',
          document_id: 'doc_1',
          document_version_id: 'ver_2',
          action: 'register_version',
          actor: '韩雨',
          detail: '登记了第 2 版',
          created_at: '2026-09-10T08:00:00+00:00',
        },
      ],
    })
    await renderPage()

    await userEvent.click(screen.getByRole('button', { name: '查看详情' }))

    const drawer = await screen.findByRole('dialog', { name: '储能行业 2026 年中期策略' })
    expect(within(drawer).getByText('版本历史')).toBeInTheDocument()
    expect(within(drawer).getByText('v2')).toBeInTheDocument()
    expect(within(drawer).getByText('已被新版本替代')).toBeInTheDocument()
    expect(within(drawer).getByText('失败（可重试）')).toBeInTheDocument()
    expect(within(drawer).getByText('解析服务不可用')).toBeInTheDocument()
    expect(within(drawer).getByText(/登记了第 2 版/)).toBeInTheDocument()
    expect(api.fetchDocument).toHaveBeenCalledWith('doc_1')
  })

  it('previews and archives a version from the drawer', async () => {
    vi.mocked(api.fetchSource).mockResolvedValue({
      blob: new Blob(['储能原文'], { type: 'text/plain' }),
      filename: '储能报告.txt',
      contentType: 'text/plain',
    })
    vi.mocked(api.archiveVersion).mockResolvedValue(aVersion({ status: 'ARCHIVED' }))
    await renderPage()
    await nameActor()
    await userEvent.click(screen.getByRole('button', { name: '查看详情' }))
    const drawer = await screen.findByRole('dialog', { name: '储能行业 2026 年中期策略' })

    await userEvent.click(within(drawer).getByRole('button', { name: '下载原件' }))
    await waitFor(() => expect(api.fetchSource).toHaveBeenCalledWith('doc_1', 'ver_1'))

    await userEvent.click(within(drawer).getByRole('button', { name: '归档此版本' }))
    await waitFor(() => expect(api.archiveVersion).toHaveBeenCalledWith('doc_1', 'ver_1', { actor: '韩雨' }))
  })

  it('asks for confirmation before deleting a document', async () => {
    vi.mocked(api.fetchDocuments)
      .mockResolvedValueOnce(listResponse([{ document: aDocument(), versions: [aVersion()], latest_job: aJob() }]))
      .mockResolvedValue(
        listResponse([
          {
            document: aDocument({ deleted_at: '2026-09-10T00:00:00+00:00' }),
            versions: [aVersion()],
            latest_job: aJob(),
          },
        ]),
      )
    vi.mocked(api.softDeleteDocument).mockResolvedValue({
      document: aDocument({ deleted_at: '2026-09-10T00:00:00+00:00' }),
    })
    await renderPage()
    await nameActor()

    await userEvent.click(screen.getByRole('button', { name: '删除资料' }))
    const confirm = await screen.findByRole('dialog', { name: '确认删除这份资料' })
    expect(api.softDeleteDocument).not.toHaveBeenCalled()

    await userEvent.click(within(confirm).getByRole('button', { name: '删除' }))

    await waitFor(() => expect(api.softDeleteDocument).toHaveBeenCalledWith('doc_1', '韩雨'))
    await waitFor(() => expect(api.fetchDocuments).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('button', { name: '删除资料' })).not.toBeInTheDocument()
  })

  it('restores a deleted document', async () => {
    vi.mocked(api.fetchDocuments).mockResolvedValue(
      listResponse([
        {
          document: aDocument({ deleted_at: '2026-09-10T00:00:00+00:00', purge_after: '2026-10-10T00:00:00+00:00' }),
          versions: [aVersion()],
          latest_job: aJob(),
        },
      ]),
    )
    vi.mocked(api.restoreDocument).mockResolvedValue(aDocument())
    await renderPage()
    await nameActor()

    expect(screen.getByText('已删除')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '恢复资料' }))

    await waitFor(() => expect(api.restoreDocument).toHaveBeenCalledWith('doc_1', { actor: '韩雨' }))
  })

  it('requires a named actor for governance and keeps the browsing controls usable', async () => {
    vi.mocked(api.fetchSource).mockResolvedValue({
      blob: new Blob(['储能原文'], { type: 'text/plain' }),
      filename: '储能报告.txt',
      contentType: 'text/plain',
    })
    await renderPage()

    expect(screen.getByRole('button', { name: '上传资料' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '删除资料' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '查看详情' })).toBeEnabled()

    await nameActor()
    expect(screen.getByRole('button', { name: '上传资料' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '删除资料' })).toBeEnabled()
  })

  it('opens and closes the drawer with the keyboard alone', async () => {
    await renderPage()

    screen.getByRole('button', { name: '查看详情' }).focus()
    await userEvent.keyboard('{Enter}')

    expect(await screen.findByRole('dialog', { name: '储能行业 2026 年中期策略' })).toBeVisible()

    await userEvent.keyboard('{Escape}')
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: '储能行业 2026 年中期策略' })).not.toBeInTheDocument(),
    )
  })
})
