import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { OperationsSummary } from '../../operationsApi'
import OperationsMetricGrid from './OperationsMetricGrid'
import OperationsReadinessPanel from './OperationsReadinessPanel'
import OperationsTrendPanel from './OperationsTrendPanel'
import RecentRunsTable from './RecentRunsTable'

const summary: OperationsSummary = {
  database: { backend: 'postgresql', name: 'sectorpulse' },
  llm: { provider: 'openai-compatible', model: 'model-a', budget_cny_per_run: '2.00', configured: true },
  consent: { live_data: true, live_llm: true },
  providers: { live_data_available: true, missing_requirements: [] },
  runs: { total: 1, running: 0, awaiting_review: 1, failed: 0, recent: [] },
  summary: { total: 12, completed_today: 3, active: 2, attention: 1 },
  trend: {
    available: true,
    reason: null,
    points: Array.from({ length: 10 }, (_, index) => ({
      date: `2026-08-${String(18 + index).padStart(2, '0')}`,
      total: index + 1,
      completed: Math.max(0, index - 1),
      failed: index === 5 ? 1 : 0,
    })),
  },
  readiness: {
    database: { status: 'ready', label: '数据库', detail: 'PostgreSQL 已连接', detail_path: '/system' },
    live_data: { status: 'ready', label: '实时数据', detail: 'Provider 与授权已就绪', detail_path: '/system' },
    llm: { status: 'warning', label: 'LLM', detail: '尚未确认实时 LLM 授权', detail_path: '/system' },
    scheduler: { status: 'disabled', label: '调度器', detail: '当前配置为停用', detail_path: '/system' },
  },
  recent_runs: [
    {
      run_id: 'data-run-id', kind: 'data', mode: '盘后复盘', status: 'FETCHING_NEWS', provider: 'live',
      requested_at: '2026-08-27T12:00:00+08:00', finished_at: null, elapsed_ms: null,
      total_cost_cny: null, candidate_count: null, detail_path: '/data-runs/data-run-id',
    },
    {
      run_id: 'content-run-id', kind: 'content', mode: '内容生成', status: 'READY_FOR_HUMAN_REVIEW', provider: 'fixture',
      requested_at: '2026-08-27T11:00:00+08:00', finished_at: '2026-08-27T11:01:00+08:00', elapsed_ms: 60_000,
      total_cost_cny: '0.2', candidate_count: 3, detail_path: '/runs/content-run-id',
    },
  ],
  generated_at: '2026-08-27T12:00:00+00:00',
}

describe('operations dashboard components', () => {
  it('renders four real metric conclusions', () => {
    render(<OperationsMetricGrid summary={summary.summary} />)

    const metrics = screen.getByRole('region', { name: '核心运营指标' })
    expect(within(metrics).getByRole('article', { name: '运行总数' })).toHaveTextContent('12')
    expect(within(metrics).getByRole('article', { name: '今日已完成' })).toHaveTextContent('3')
    expect(within(metrics).getByRole('article', { name: '运行中' })).toHaveTextContent('2')
    expect(within(metrics).getByRole('article', { name: '异常与待处理' })).toHaveTextContent('1')
  })

  it('switches the real trend between seven and thirty day windows', () => {
    render(<OperationsTrendPanel trend={summary.trend} generatedAt={summary.generated_at} />)

    expect(screen.getByRole('button', { name: '近 7 天' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('最近 7 天共 49 次运行')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '近 30 天' }))

    expect(screen.getByRole('button', { name: '近 30 天' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('最近 30 天共 55 次运行')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '最近 30 天运行趋势' })).toBeInTheDocument()
  })

  it('shows the backend reason instead of drawing an unavailable trend', () => {
    render(<OperationsTrendPanel trend={{ available: false, reason: '最近 30 天没有运行记录', points: [] }} generatedAt={summary.generated_at} />)

    expect(screen.getByText('最近 30 天没有运行记录')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('renders all readiness items with one real system link', () => {
    render(<MemoryRouter><OperationsReadinessPanel readiness={summary.readiness} /></MemoryRouter>)

    const panel = screen.getByRole('region', { name: '系统就绪状态' })
    expect(within(panel).getByText('PostgreSQL 已连接')).toBeInTheDocument()
    expect(within(panel).getByText('尚未确认实时 LLM 授权')).toBeInTheDocument()
    expect(within(panel).getByText('当前配置为停用')).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: '查看系统详情' })).toHaveAttribute('href', '/system')
  })

  it('routes each recent run to its real detail page and preserves unknown values', () => {
    render(<MemoryRouter><RecentRunsTable runs={summary.recent_runs} /></MemoryRouter>)

    expect(screen.getByRole('link', { name: /data-run/ })).toHaveAttribute('href', '/data-runs/data-run-id')
    expect(screen.getByRole('link', { name: /content-/ })).toHaveAttribute('href', '/runs/content-run-id')
    const dataRow = screen.getByRole('link', { name: /data-run/ }).closest('tr')
    expect(dataRow).toHaveTextContent('暂无')
    expect(dataRow).not.toHaveTextContent('0 个')
  })

  it('teaches the empty recent-runs state without inventing rows', () => {
    render(<MemoryRouter><RecentRunsTable runs={[]} /></MemoryRouter>)

    expect(screen.getByRole('heading', { name: '还没有运行记录' })).toBeInTheDocument()
    expect(screen.queryByRole('row')).not.toBeInTheDocument()
  })
})
