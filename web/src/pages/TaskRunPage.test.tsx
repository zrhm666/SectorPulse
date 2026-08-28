import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TaskRunPage from './TaskRunPage'
import * as api from '../schedulesApi'

vi.mock('../schedulesApi')

describe('TaskRunPage', () => {
  beforeEach(() => vi.clearAllMocks())
  it('shows retryable error and stage history', async () => {
    vi.mocked(api.fetchTaskRun).mockResolvedValue({
      run_id: 'run-1', status: 'RETRY_WAITING', provider: 'fixture', input_fingerprint: 'hash',
      stages: [{ stage: 'FETCHING_MARKET', attempt_no: 1, status: 'FAILED', error_code: 'TASK_PROVIDER_TRANSIENT' }],
      events: [{ event_type: 'TASK_RETRY_SCHEDULED', summary: '等待下一次自动尝试', created_at: '2026-08-28T10:00:00Z' }], downgrade_reasons: [],
    })
    render(
      <MemoryRouter initialEntries={['/task-runs/run-1']}>
        <Routes><Route path="/task-runs/:runId" element={<TaskRunPage />} /></Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByText('阶段历史')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '任务阶段' })).toBeVisible()
    expect(screen.getByText('等待下一次自动尝试')).toBeVisible()
    expect(screen.queryByRole('button', { name: '重试' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '恢复' })).not.toBeInTheDocument()
  })

  it('shows an explicit load error and can retry the request', async () => {
    vi.mocked(api.fetchTaskRun)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ run_id: 'run-1', status: 'COMPLETED', provider: 'fixture', input_fingerprint: 'hash', stages: [], events: [], downgrade_reasons: [] })
    render(<MemoryRouter initialEntries={['/task-runs/run-1']}><Routes><Route path="/task-runs/:runId" element={<TaskRunPage />} /></Routes></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: '重新加载' }))
    expect(await screen.findByText('阶段历史')).toBeVisible()
    expect(api.fetchTaskRun).toHaveBeenCalledTimes(2)
  })
})
