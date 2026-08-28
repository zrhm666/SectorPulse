import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createRun, fetchFixtureInput } from '../api'
import { createDataRun } from '../dataRunsApi'
import { fetchOperationsSummary } from '../operationsApi'
import NewAnalysisPage from './NewAnalysisPage'

vi.mock('../api', () => ({ createRun: vi.fn(), fetchFixtureInput: vi.fn() }))
vi.mock('../dataRunsApi', () => ({ createDataRun: vi.fn() }))
vi.mock('../operationsApi', () => ({ fetchOperationsSummary: vi.fn() }))

const readySummary = {
  database: { backend: 'postgresql' as const, name: 'sector_pulse' },
  llm: { provider: 'openai', model: 'test-model', budget_cny_per_run: '2', configured: true },
  consent: { live_data: true, live_llm: true },
  providers: { live_data_available: true, missing_requirements: [] },
  runs: { total: 0, running: 0, awaiting_review: 0, failed: 0, recent: [] },
  summary: { total: 0, completed_today: 0, active: 0, attention: 0 },
  trend: { available: false, reason: '当前还没有可用于趋势统计的运行记录', points: [] },
  readiness: {
    database: { status: 'ready' as const, label: '数据库', detail: 'PostgreSQL 已连接', detail_path: '/system' },
    live_data: { status: 'ready' as const, label: '实时数据', detail: 'Provider 与授权已就绪', detail_path: '/system' },
    llm: { status: 'ready' as const, label: 'LLM', detail: 'openai 已就绪', detail_path: '/system' },
    scheduler: { status: 'disabled' as const, label: '调度器', detail: '当前配置为停用', detail_path: '/system' },
  },
  recent_runs: [],
  generated_at: '2026-08-27T12:00:00+00:00',
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/runs/new']}>
      <Routes>
        <Route path="/runs/new" element={<NewAnalysisPage />} />
        <Route path="/runs/:runId" element={<div>内容运行详情</div>} />
        <Route path="/data-runs/:runId" element={<div>数据运行详情</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('NewAnalysisPage', () => {
  beforeEach(() => {
    vi.mocked(fetchOperationsSummary).mockResolvedValue(readySummary)
    vi.mocked(fetchFixtureInput).mockResolvedValue({ requested_at: '2026-08-23T00:00:00Z' })
    vi.mocked(createRun).mockResolvedValue({ run_id: 'fixture-run' })
    vi.mocked(createDataRun).mockResolvedValue({ run_id: 'live-run' })
  })

  it('creates a fixture run through the four-step flow and submits only real parameters', async () => {
    renderPage()
    expect(await screen.findByRole('heading', { name: '新建分析' })).toBeVisible()
    const progress = screen.getByRole('list', { name: '新建分析进度' })
    expect(within(progress).getByText('场景').closest('li')).toHaveAttribute('aria-current', 'step')
    expect(within(progress).getAllByRole('listitem')).toHaveLength(4)
    fireEvent.click(screen.getByRole('button', { name: /盘后复盘/ }))
    fireEvent.click(screen.getByRole('button', { name: '下一步：选择执行方式' }))
    fireEvent.click(screen.getByRole('button', { name: /Fixture 演练/ }))
    fireEvent.click(screen.getByRole('button', { name: '下一步：确认参数' }))
    expect(screen.getByText('内置可复现样例')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '下一步：启动' }))
    fireEvent.click(screen.getByRole('button', { name: '启动 Fixture 分析' }))

    expect(await screen.findByText('内容运行详情')).toBeVisible()
    expect(fetchFixtureInput).toHaveBeenCalledOnce()
    expect(createRun).toHaveBeenCalledWith(expect.any(Object), 'fixture')
  })

  it('blocks live submission when consent or provider requirements are missing', async () => {
    vi.mocked(fetchOperationsSummary).mockResolvedValue({
      ...readySummary,
      consent: { live_data: false, live_llm: false },
      providers: { live_data_available: false, missing_requirements: ['missing live-data-consent'] },
    })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /盘中分析/ }))
    fireEvent.click(screen.getByRole('button', { name: '下一步：选择执行方式' }))
    fireEvent.click(screen.getByRole('button', { name: /Live 实时运行/ }))

    expect(screen.getByText(/创建 .live-data-consent/)).toBeVisible()
    expect(screen.getByText(/创建 .live-llm-consent/)).toBeVisible()
    expect(screen.getByRole('button', { name: '下一步：确认参数' })).toBeDisabled()
    await waitFor(() => expect(createDataRun).not.toHaveBeenCalled())
  })

  it('retains choices when moving backward and prevents duplicate submission', async () => {
    let resolveCreate!: (value: { run_id: string }) => void
    const pendingCreate = new Promise<{ run_id: string }>((resolve) => { resolveCreate = resolve })
    vi.mocked(createRun).mockReturnValue(pendingCreate)
    renderPage()
    await screen.findByRole('button', { name: /盘中分析/ })
    fireEvent.click(screen.getByRole('button', { name: /盘后复盘/ }))
    fireEvent.click(screen.getByRole('button', { name: '下一步：选择执行方式' }))
    fireEvent.click(screen.getByRole('button', { name: /Fixture 演练/ }))
    fireEvent.click(screen.getByRole('button', { name: '下一步：确认参数' }))
    fireEvent.click(screen.getByRole('button', { name: '上一步' }))
    expect(screen.getByRole('button', { name: /Fixture 演练/ })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: '下一步：确认参数' }))
    fireEvent.click(screen.getByRole('button', { name: '下一步：启动' }))
    const submit = screen.getByRole('button', { name: '启动 Fixture 分析' })
    fireEvent.click(submit)
    fireEvent.click(submit)
    expect(createRun).toHaveBeenCalledOnce()
    expect(screen.getByRole('button', { name: '正在启动…' })).toBeDisabled()
    await act(async () => { resolveCreate({ run_id: 'fixture-run' }) })
    expect(await screen.findByText('内容运行详情')).toBeVisible()
  })
})
