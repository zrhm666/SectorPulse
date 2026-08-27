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
  summary: { total: 3, completed_today: 1, active: 1, attention: 1 },
  trend: { available: true, reason: null, points: [{ date: '2026-08-23', total: 3, completed: 1, failed: 0 }] },
  readiness: {
    database: { status: 'ready' as const, label: '数据库', detail: 'PostgreSQL 已连接', detail_path: '/system' },
    live_data: { status: 'ready' as const, label: '实时数据', detail: 'Provider 与授权已就绪', detail_path: '/system' },
    llm: { status: 'warning' as const, label: 'LLM', detail: '尚未确认实时 LLM 授权', detail_path: '/system' },
    scheduler: { status: 'disabled' as const, label: '调度器', detail: '当前配置为停用', detail_path: '/system' },
  },
  recent_runs: [],
  generated_at: '2026-08-27T12:00:00+00:00',
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
    expect(screen.getByRole('region', { name: '运营指标' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '最近运行' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '运行条件' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '新建分析' })).toHaveClass('button-primary')
    expect(screen.getByRole('button', { name: '刷新状态' })).toHaveClass('button-secondary')
  })

  it('shows a recovery action when the summary request fails', async () => {
    vi.mocked(operationsApi.fetchOperationsSummary).mockRejectedValue(new Error('offline'))

    render(<MemoryRouter><OperationsDashboardPage /></MemoryRouter>)

    expect(await screen.findByRole('alert')).toHaveTextContent('无法加载运营概览')
    expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument()
  })
})
