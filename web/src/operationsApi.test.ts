import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchOperationsSummary } from './operationsApi'

describe('fetchOperationsSummary', () => {
  afterEach(() => vi.restoreAllMocks())

  it('loads the redacted operations summary', async () => {
    const payload = {
      database: { backend: 'postgresql', name: 'runtime' },
      llm: { provider: 'fixture', model: null, budget_cny_per_run: '2.00', configured: true },
      consent: { live_data: false, live_llm: false },
      providers: { live_data_available: false, missing_requirements: ['.live-data-consent'] },
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
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), { status: 200 }),
    ))

    await expect(fetchOperationsSummary()).resolves.toMatchObject({
      database: { backend: 'postgresql', name: 'runtime' },
    })
    expect(fetch).toHaveBeenCalledWith('/api/operations/summary', { signal: undefined })
  })

  it('rejects an unsuccessful response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })))

    await expect(fetchOperationsSummary()).rejects.toThrow('运营摘要请求失败（HTTP 503）')
  })
})
