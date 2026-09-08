import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchRun } from '../api'
import RunDetailPage from './RunDetailPage'

vi.mock('../api', () => ({
  fetchRun: vi.fn(),
  retryRun: vi.fn(),
}))

vi.mock('../useRuns', () => ({
  useRunSSE: () => ({ events: [], done: true, error: null }),
}))

vi.mock('./tabs/OverviewTab', () => ({ default: () => <div>概览内容</div> }))
vi.mock('./tabs/RadarTab', () => ({ default: () => <div>雷达内容</div> }))
vi.mock('./tabs/DraftTab', () => ({ default: () => <div>草稿内容</div> }))
vi.mock('./tabs/EvidenceTab', () => ({ default: () => <div>证据内容</div> }))
vi.mock('./tabs/ReviewTab', () => ({ default: () => <div>审核内容</div> }))
vi.mock('./tabs/GovernanceTab', () => ({ default: () => <div>治理内容</div> }))

describe('RunDetailPage', () => {
  beforeEach(() => {
    vi.mocked(fetchRun).mockResolvedValue({
      run_id: 'run-1',
      requested_at: '2026-08-17T00:00:00Z',
      provider: 'fixture',
      status: 'READY_FOR_HUMAN_REVIEW',
      elapsed_ms: 120,
      total_cost_cny: '0',
      draft_id: 'draft-1',
      sector_count: 8,
      retryable: true,
    })
  })

  it('loads and renders a completed historical run on mount', async () => {
    render(
      <MemoryRouter initialEntries={['/runs/run-1']}>
        <Routes>
          <Route path="/runs/:runId" element={<RunDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('待人工审核')).toBeVisible()
    expect(screen.getByText('样例演练')).toBeVisible()
    expect(screen.getByRole('button', { name: '重新运行' })).toBeEnabled()
    expect(screen.getByRole('tab', { name: '治理' })).toBeVisible()
    expect(screen.getByRole('region', { name: '内容运行摘要' })).toHaveTextContent('板块数')
    expect(screen.getByRole('region', { name: '运行阶段' })).toBeVisible()
    expect(screen.getByRole('link', { name: '进入审核工作台' })).toHaveAttribute('href', '/review?run=run-1')
    await waitFor(() => expect(fetchRun).toHaveBeenCalledWith('run-1'))
  })

  it('does not describe missing terminal metrics as pending or zero', async () => {
    vi.mocked(fetchRun).mockResolvedValue({ run_id: 'run-1', requested_at: '2026-08-17T00:00:00Z', provider: 'live', status: 'FAILED', elapsed_ms: null, total_cost_cny: null, draft_id: null })
    render(<MemoryRouter initialEntries={['/runs/run-1']}><Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes></MemoryRouter>)
    const summary = await screen.findByRole('region', { name: '内容运行摘要' })
    expect(summary).not.toHaveTextContent('待完成')
    expect(summary.textContent?.match(/未记录/g)).toHaveLength(3)
  })

  it('returns to the filtered registry when opened from its list', async () => {
    render(<MemoryRouter initialEntries={[{ pathname: '/runs/run-1', state: { registryReturnTo: '/runs?status=FAILED&page=2' } }]}><Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes></MemoryRouter>)
    expect(await screen.findByRole('link', { name: '返回运行历史' })).toHaveAttribute('href', '/runs?status=FAILED&page=2')
  })

  it('keeps a stored draft reachable when the run status is failed', async () => {
    vi.mocked(fetchRun).mockResolvedValue({
      run_id: 'run-1', requested_at: '2026-08-17T00:00:00Z', provider: 'live', status: 'FAILED',
      elapsed_ms: 120, total_cost_cny: '0', draft_id: 'draft-1', sector_count: 8, retryable: true,
      error_message: '审核服务暂时不可用', input_json_hash: 'snapshot-hash',
    })
    render(<MemoryRouter initialEntries={['/runs/run-1']}><Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes></MemoryRouter>)
    await userEvent.click(await screen.findByRole('tab', { name: '草稿' }))
    expect(await screen.findByText('草稿内容')).toBeInTheDocument()
    expect(screen.getByText('审核服务暂时不可用')).toBeVisible()
    expect(screen.getByText(/已保留输入快照/)).toBeVisible()
    expect(screen.queryByText('已完成')).not.toBeInTheDocument()
  })
})
