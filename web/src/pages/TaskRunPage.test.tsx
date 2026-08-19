import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TaskRunPage from './TaskRunPage'
import * as api from '../schedulesApi'

vi.mock('../schedulesApi')

describe('TaskRunPage', () => {
  it('shows retryable error and stage history', async () => {
    vi.mocked(api.fetchTaskRun).mockResolvedValue({
      run_id: 'run-1', status: 'RETRY_WAITING', provider: 'fixture', input_fingerprint: 'hash',
      stages: [{ stage: 'FETCHING_MARKET', attempt_no: 1, status: 'FAILED', error_code: 'TASK_PROVIDER_TRANSIENT' }],
      events: [], downgrade_reasons: [],
    })
    render(
      <MemoryRouter initialEntries={['/task-runs/run-1']}>
        <Routes><Route path="/task-runs/:runId" element={<TaskRunPage />} /></Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByText('阶段历史')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
  })
})
