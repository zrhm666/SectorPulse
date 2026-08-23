import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import OperationsDashboardPage from './OperationsDashboardPage'
import * as operationsApi from '../operationsApi'

vi.mock('../operationsApi')

const summary = {
  database: { backend: 'postgresql' as const, name: 'sectorpulse_runtime' },
  llm: { provider: 'openai-compatible', model: 'model-a', budget_cny_per_run: '2.00', configured: true },
  consent: { live_data: true, live_llm: false },
  providers: { live_data_available: true, missing_requirements: [] },
  runs: {
    total: 3,
    running: 1,
    awaiting_review: 1,
    failed: 0,
    recent: [{ run_id: '12345678-0000-0000-0000-000000000000', requested_at: '2026-08-23T09:00:00+08:00', provider: 'fixture', status: 'READY_FOR_HUMAN_REVIEW', elapsed_ms: 1200, total_cost_cny: '0', draft_id: null }],
  },
}

describe('OperationsDashboardPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(operationsApi.fetchOperationsSummary).mockResolvedValue(summary)
  })

  it('shows a loading state while the live summary is requested', () => {
    vi.mocked(operationsApi.fetchOperationsSummary).mockReturnValue(new Promise(() => undefined))

    render(<MemoryRouter><OperationsDashboardPage /></MemoryRouter>)

    expect(screen.getByRole('status')).toHaveTextContent('正在加载运营概览')
  })

  it('renders real status metrics and the most recent run', async () => {
    render(<MemoryRouter><OperationsDashboardPage /></MemoryRouter>)

    expect(await screen.findByRole('heading', { level: 1, name: '运营总览' })).toBeInTheDocument()
    expect(screen.getByText('待复核')).toBeInTheDocument()
    expect(screen.getByText('12345678')).toBeInTheDocument()
    expect(screen.getByText('PostgreSQL 已连接')).toBeInTheDocument()
    expect(screen.getByText(/最后更新/)).toBeInTheDocument()
  })

  it('shows a recovery action when the summary request fails', async () => {
    vi.mocked(operationsApi.fetchOperationsSummary).mockRejectedValue(new Error('offline'))

    render(<MemoryRouter><OperationsDashboardPage /></MemoryRouter>)

    expect(await screen.findByRole('alert')).toHaveTextContent('无法加载运营概览')
    expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument()
  })
})
