import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { OperationsSummary } from '../operationsApi'
import useOperationsSummary, { type OperationsSummaryState } from '../hooks/useOperationsSummary'
import OperationsDashboardPage from './OperationsDashboardPage'

vi.mock('../hooks/useOperationsSummary')

const summary: OperationsSummary = {
  database: { backend: 'postgresql', name: 'sectorpulse_runtime' },
  llm: { provider: 'openai-compatible', model: 'model-a', budget_cny_per_run: '2.00', configured: true },
  consent: { live_data: true, live_llm: false },
  providers: { live_data_available: true, missing_requirements: [] },
  runs: { total: 1, running: 1, awaiting_review: 0, failed: 0, recent: [] },
  summary: { total: 12, completed_today: 3, active: 2, attention: 1 },
  trend: { available: true, reason: null, points: [{ date: '2026-08-27', total: 3, completed: 1, failed: 0 }] },
  readiness: {
    database: { status: 'ready', label: '数据库', detail: 'PostgreSQL 已连接', detail_path: '/system' },
    live_data: { status: 'ready', label: '实时数据', detail: 'Provider 与授权已就绪', detail_path: '/system' },
    llm: { status: 'warning', label: 'LLM', detail: '尚未确认实时 LLM 授权', detail_path: '/system' },
    scheduler: { status: 'disabled', label: '调度器', detail: '当前配置为停用', detail_path: '/system' },
  },
  recent_runs: [{
    run_id: '12345678-0000-0000-0000-000000000000', kind: 'content', mode: '内容生成',
    status: 'READY_FOR_HUMAN_REVIEW', provider: 'fixture', requested_at: '2026-08-27T09:00:00+08:00',
    finished_at: '2026-08-27T09:01:00+08:00', elapsed_ms: 60_000, total_cost_cny: '0',
    candidate_count: 3, detail_path: '/runs/12345678-0000-0000-0000-000000000000',
  }],
  generated_at: '2026-08-27T12:00:00+00:00',
}

const refresh = vi.fn(async () => undefined)

function state(overrides: Partial<OperationsSummaryState> = {}): OperationsSummaryState {
  return {
    data: summary, initialLoading: false, refreshing: false, stale: false, error: null,
    lastSuccessfulAt: new Date('2026-08-27T12:00:00+08:00'), refresh, ...overrides,
  }
}

describe('OperationsDashboardPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(useOperationsSummary).mockReturnValue(state())
  })

  it('shows a loading state while the first live summary is requested', () => {
    vi.mocked(useOperationsSummary).mockReturnValue(state({ data: null, initialLoading: true, lastSuccessfulAt: null }))
    render(<MemoryRouter><OperationsDashboardPage /></MemoryRouter>)
    expect(screen.getByRole('status')).toHaveTextContent('正在加载运营概览')
  })

  it('composes metrics, trend, readiness, and recent runs from the real summary', () => {
    render(<MemoryRouter><OperationsDashboardPage /></MemoryRouter>)
    expect(screen.getByRole('heading', { level: 1, name: '运营总览' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '核心运营指标' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '运行趋势' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '系统就绪状态' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '最近运行' })).toBeInTheDocument()
    expect(screen.getByText('PostgreSQL 已连接')).toBeInTheDocument()
    expect(screen.getByText('12345678')).toBeInTheDocument()
  })

  it('shows a recovery action when the first request fails', () => {
    vi.mocked(useOperationsSummary).mockReturnValue(state({ data: null, initialLoading: false, error: '运营数据刷新失败，请稍后重试', lastSuccessfulAt: null }))
    render(<MemoryRouter><OperationsDashboardPage /></MemoryRouter>)
    expect(screen.getByRole('alert')).toHaveTextContent('无法加载运营概览')
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(refresh).toHaveBeenCalledOnce()
  })

  it('keeps the last successful data visible when a refresh fails', () => {
    vi.mocked(useOperationsSummary).mockReturnValue(state({ stale: true, error: '运营数据刷新失败，请稍后重试' }))
    render(<MemoryRouter><OperationsDashboardPage /></MemoryRouter>)
    expect(screen.getByRole('alert')).toHaveTextContent('当前显示上次成功数据')
    expect(screen.getByRole('region', { name: '核心运营指标' })).toBeInTheDocument()
  })

  it('exposes refresh progress without replacing dashboard content', () => {
    vi.mocked(useOperationsSummary).mockReturnValue(state({ refreshing: true }))
    render(<MemoryRouter><OperationsDashboardPage /></MemoryRouter>)
    expect(screen.getByRole('button', { name: '正在刷新' })).toBeDisabled()
    expect(screen.getByRole('region', { name: '最近运行' })).toBeInTheDocument()
  })
})
