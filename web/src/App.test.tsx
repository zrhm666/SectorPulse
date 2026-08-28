import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import * as api from './api'
import * as operationsApi from './operationsApi'

vi.mock('./api')
vi.mock('./dataRunsApi')
vi.mock('./operationsApi')

describe('App routes', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.fetchRuns).mockResolvedValue([])
    vi.mocked(operationsApi.fetchOperationsSummary).mockResolvedValue({
      database: { backend: 'postgresql', name: 'runtime' },
      llm: { provider: 'fixture', model: null, budget_cny_per_run: '2.00', configured: true },
      consent: { live_data: false, live_llm: false },
      providers: { live_data_available: false, missing_requirements: ['live-data-consent'] },
      runs: { total: 0, running: 0, awaiting_review: 0, failed: 0, recent: [] },
      summary: { total: 0, completed_today: 0, active: 0, attention: 0 },
      trend: { available: false, reason: '当前还没有可用于趋势统计的运行记录', points: [] },
      readiness: {
        database: { status: 'ready', label: '数据库', detail: 'PostgreSQL 已连接', detail_path: '/system' },
        live_data: { status: 'unavailable', label: '实时数据', detail: '缺少授权', detail_path: '/system' },
        llm: { status: 'ready', label: 'LLM', detail: 'fixture 已就绪', detail_path: '/system' },
        scheduler: { status: 'disabled', label: '调度器', detail: '当前配置为停用', detail_path: '/system' },
      },
      recent_runs: [],
      generated_at: '2026-08-27T12:00:00+00:00',
    })
  })

  it('renders the operations dashboard on the root route', async () => {
    window.history.pushState({}, '', '/')

    render(<App />)

    expect(await screen.findByRole('heading', { level: 1, name: '运营总览' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '运营总览' })).toHaveAttribute('aria-current', 'page')
  })

  it('renders the system status route inside the navigation shell', async () => {
    window.history.pushState({}, '', '/system')

    render(<App />)

    expect(await screen.findByRole('heading', { level: 1, name: '系统状态' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '系统状态' })).toHaveAttribute('aria-current', 'page')
  })

  it('renders the runs route inside the main navigation shell', async () => {
    window.history.pushState({}, '', '/runs')

    render(<App />)

    expect(await screen.findByRole('heading', { level: 1, name: '分析运行' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: '主导航' })).toBeInTheDocument()
  })

  it('shows a loading state while runs are being requested', () => {
    vi.mocked(api.fetchRuns).mockReturnValue(new Promise(() => undefined))
    window.history.pushState({}, '', '/runs')

    render(<App />)

    expect(screen.getByRole('status')).toHaveTextContent('正在加载运行记录')
  })

  it('shows a request error instead of an empty run list', async () => {
    vi.mocked(api.fetchRuns).mockRejectedValue(new Error('offline'))
    window.history.pushState({}, '', '/runs')

    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent('无法加载运行记录')
  })

  it('shows a guided empty state after a successful empty response', async () => {
    window.history.pushState({}, '', '/runs')

    render(<App />)

    expect(await screen.findByRole('heading', { level: 2, name: '还没有运行记录' })).toBeInTheDocument()
  })
})
