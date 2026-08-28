import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import * as api from '../api'
import * as editing from '../editingApi'
import FeedbackProvider from '../components/ui/FeedbackProvider'
import ReviewWorkspacePage from './ReviewWorkspacePage'

vi.mock('../api')
vi.mock('../editingApi')

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchRuns).mockResolvedValue([{ run_id: 'run-1', requested_at: '2026-08-23T01:00:00Z', provider: 'fixture', status: 'READY_FOR_HUMAN_REVIEW', elapsed_ms: 100, total_cost_cny: '0', draft_id: 'draft-1' }])
  vi.mocked(api.fetchDraft).mockResolvedValue({ versions: [{ version: 1, status: 'READY_FOR_HUMAN_REVIEW', titles: ['旧标题'], introduction: '旧导语', sections: [{ section_id: 'section-1', heading: '板块', body: '旧正文' }], conclusion: '旧结论', risk_notice: '旧风险', sources: [{ source_id: 'source-1', title: '来源', citation_url: 'https://example.test' }], character_count: 1000 }, { version: 2, status: 'READY_FOR_HUMAN_REVIEW', titles: ['新标题'], introduction: '新导语', sections: [{ section_id: 'section-1', heading: '板块', body: '新正文' }], conclusion: '新结论', risk_notice: '新风险', sources: [{ source_id: 'source-1', title: '来源', citation_url: 'https://example.test' }], character_count: 1000 }] })
  vi.mocked(api.fetchEvidence).mockResolvedValue({ sectors: [], events: [], invocations: [] })
  vi.mocked(editing.fetchGovernance).mockResolvedValue({ status: 'PASS', issues: [], rules_version: 'v1' })
  vi.mocked(editing.fetchApproval).mockResolvedValue(null)
  vi.mocked(editing.fetchEvidenceDecisions).mockResolvedValue([])
})

it('loads the review queue and edits only the latest draft version', async () => {
  render(<MemoryRouter><FeedbackProvider><ReviewWorkspacePage /></FeedbackProvider></MemoryRouter>)
  expect(await screen.findByRole('heading', { name: '审核工作台' })).toBeVisible()
  expect(screen.getByRole('region', { name: '审核队列' })).toBeVisible()
  const evidence = await screen.findByRole('complementary', { name: '证据与治理' })
  const editor = screen.getByRole('main', { name: '草稿编辑区' })
  const workspace = screen.getByRole('region', { name: '审核主工作区' })
  expect(workspace).toContainElement(editor)
  expect(workspace).toContainElement(evidence)
  expect(workspace).toContainElement(screen.getByRole('region', { name: '审核队列' }))
  expect(screen.getByRole('tablist', { name: '审核工作区视图' })).toBeInTheDocument()
  expect(screen.getByRole('tabpanel', { name: '队列' })).toHaveAttribute('data-pane', 'queue')
  expect(screen.getByRole('tabpanel', { name: '草稿' })).toHaveAttribute('data-active', 'true')
  expect(screen.getByRole('tabpanel', { name: '证据' })).toHaveAttribute('data-pane', 'evidence')
  expect(screen.getByRole('button', { name: /run-1/ })).toBeVisible()
  expect(screen.getByRole('button', { name: /run-1/ })).toHaveTextContent('板块数未提供')
  expect(await screen.findByDisplayValue('新正文')).toBeEnabled()
  expect(screen.getByText('当前编辑版本 v2')).toBeVisible()
})

it('reports approval failures without leaving an unhandled action', async () => {
  vi.mocked(editing.approveDraft).mockRejectedValue(new Error('conflict'))
  render(<MemoryRouter><FeedbackProvider><ReviewWorkspacePage /></FeedbackProvider></MemoryRouter>)
  await screen.findByDisplayValue('新正文')

  await userEvent.click(screen.getByRole('button', { name: '批准复制' }))
  await userEvent.click(screen.getByRole('button', { name: '确认批准' }))

  expect(await screen.findByText('批准失败，请刷新草稿状态后重试。')).toBeVisible()
})

it('gates approval immediately while a field is dirty', async () => {
  render(<MemoryRouter><FeedbackProvider><ReviewWorkspacePage /></FeedbackProvider></MemoryRouter>)
  const introduction = await screen.findByLabelText('导语')
  fireEvent.change(introduction, { target: { value: '尚未保存的导语' } })

  expect(screen.getByRole('button', { name: '批准复制' })).toBeDisabled()
  expect(screen.getByText('草稿仍有未保存的修改，请等待保存完成。')).toBeVisible()
})

it('refreshes only approval state after a successful approval action', async () => {
  vi.mocked(editing.approveDraft).mockResolvedValue({ draft_id: 'draft-1', version: 2, status: 'APPROVED_FOR_COPY', actor: 'reviewer' })
  vi.mocked(editing.fetchApproval)
    .mockResolvedValueOnce(null)
    .mockResolvedValueOnce({ draft_id: 'draft-1', version: 2, status: 'APPROVED_FOR_COPY', actor: 'reviewer' })
  render(<MemoryRouter><FeedbackProvider><ReviewWorkspacePage /></FeedbackProvider></MemoryRouter>)
  await screen.findByDisplayValue('新正文')

  await userEvent.click(screen.getByRole('button', { name: '批准复制' }))
  await userEvent.click(screen.getByRole('button', { name: '确认批准' }))

  expect(await screen.findByText('草稿 v2 已批准。')).toBeVisible()
  expect(editing.fetchApproval).toHaveBeenCalledTimes(2)
  expect(api.fetchDraft).toHaveBeenCalledTimes(1)
})
