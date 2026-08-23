import { render, screen, waitFor } from '@testing-library/react'
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
    expect(screen.getByText('fixture')).toBeVisible()
    expect(screen.getByRole('button', { name: '重新运行' })).toBeEnabled()
    expect(screen.getByRole('tab', { name: '治理' })).toBeVisible()
    await waitFor(() => expect(fetchRun).toHaveBeenCalledWith('run-1'))
  })
})
