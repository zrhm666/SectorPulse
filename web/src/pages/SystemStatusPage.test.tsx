import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SystemStatusPage from './SystemStatusPage'
import * as operationsApi from '../operationsApi'

vi.mock('../operationsApi')

describe('SystemStatusPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('shows unavailable prerequisites without rendering secret values', async () => {
    vi.mocked(operationsApi.fetchOperationsSummary).mockResolvedValue({
      database: { backend: 'sqlite', name: 'local.db' },
      llm: { provider: 'openai-compatible', model: 'safe-model', budget_cny_per_run: '2.00', configured: false },
      consent: { live_data: false, live_llm: false },
      providers: { live_data_available: false, missing_requirements: ['live-data-consent'] },
      runs: { total: 0, running: 0, awaiting_review: 0, failed: 0, recent: [] },
      summary: { total: 0, completed_today: 0, active: 0, attention: 0 },
      trend: { available: false, reason: '当前还没有可用于趋势统计的运行记录', points: [] },
      readiness: {
        database: { status: 'ready', label: '数据库', detail: 'SQLite 已连接', detail_path: '/system' },
        live_data: { status: 'unavailable', label: '实时数据', detail: '缺少授权', detail_path: '/system' },
        llm: { status: 'unavailable', label: 'LLM', detail: '模型配置不完整', detail_path: '/system' },
        scheduler: { status: 'disabled', label: '调度器', detail: '当前配置为停用', detail_path: '/system' },
      },
      recent_runs: [],
      generated_at: '2026-08-27T12:00:00+00:00',
    })

    render(<SystemStatusPage />)

    expect(await screen.findByRole('heading', { level: 1, name: '系统状态' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '系统连接状态' })).toBeVisible()
    expect(screen.getByText('缺少 live-data-consent')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '调度器' })).toBeVisible()
    expect(screen.getByText(/检查时间/)).toHaveTextContent('2026')
    expect(screen.queryByText(/api[_ -]?key/i)).not.toBeInTheDocument()
  })
})
