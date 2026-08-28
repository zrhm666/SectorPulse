import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as operationsApi from '../operationsApi'
import useOperationsSummary from './useOperationsSummary'

vi.mock('../operationsApi', async () => {
  const actual = await vi.importActual<typeof import('../operationsApi')>('../operationsApi')
  return { ...actual, fetchOperationsSummary: vi.fn() }
})

const summary = {
  database: { backend: 'postgresql' as const, name: 'sectorpulse' },
  llm: { provider: 'openai-compatible', model: 'model-a', budget_cny_per_run: '2.00', configured: true },
  consent: { live_data: true, live_llm: true },
  providers: { live_data_available: true, missing_requirements: [] },
  runs: { total: 1, running: 1, awaiting_review: 0, failed: 0, recent: [] },
  summary: { total: 2, completed_today: 1, active: 1, attention: 0 },
  trend: {
    available: true,
    reason: null,
    points: [{ date: '2026-08-27', total: 2, completed: 1, failed: 0 }],
  },
  readiness: {
    database: { status: 'ready' as const, label: '数据库', detail: 'PostgreSQL 已连接', detail_path: '/system' },
    live_data: { status: 'ready' as const, label: '实时数据', detail: 'Provider 与授权已就绪', detail_path: '/system' },
    llm: { status: 'ready' as const, label: 'LLM', detail: 'openai-compatible 已就绪', detail_path: '/system' },
    scheduler: { status: 'disabled' as const, label: '调度器', detail: '当前配置为停用', detail_path: '/system' },
  },
  recent_runs: [],
  generated_at: '2026-08-27T12:00:00+00:00',
}

describe('useOperationsSummary', () => {
  let visibility: DocumentVisibilityState

  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    visibility = 'visible'
    vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility)
    vi.mocked(operationsApi.fetchOperationsSummary).mockResolvedValue(summary)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('loads the complete summary on mount', async () => {
    const { result } = renderHook(() => useOperationsSummary())

    await act(async () => { await Promise.resolve() })

    expect(result.current.initialLoading).toBe(false)
    expect(result.current.data?.summary.active).toBe(1)
    expect(result.current.error).toBeNull()
    expect(result.current.stale).toBe(false)
  })

  it('polls every five seconds only while a run is active', async () => {
    renderHook(() => useOperationsSummary())
    await act(async () => { await Promise.resolve() })

    await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
    expect(operationsApi.fetchOperationsSummary).toHaveBeenCalledTimes(2)

    vi.mocked(operationsApi.fetchOperationsSummary).mockResolvedValue({
      ...summary,
      summary: { ...summary.summary, active: 0 },
    })
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
    expect(operationsApi.fetchOperationsSummary).toHaveBeenCalledTimes(3)
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })

    expect(operationsApi.fetchOperationsSummary).toHaveBeenCalledTimes(3)
  })

  it('pauses polling while the document is hidden', async () => {
    renderHook(() => useOperationsSummary())
    await act(async () => { await Promise.resolve() })

    visibility = 'hidden'
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })

    expect(operationsApi.fetchOperationsSummary).toHaveBeenCalledTimes(1)
  })

  it('retains the last successful summary when a refresh fails', async () => {
    const { result } = renderHook(() => useOperationsSummary())
    await act(async () => { await Promise.resolve() })
    expect(result.current.data).toEqual(summary)
    vi.mocked(operationsApi.fetchOperationsSummary).mockRejectedValueOnce(new Error('offline'))

    await act(async () => { await result.current.refresh() })

    expect(result.current.data).toEqual(summary)
    expect(result.current.stale).toBe(true)
    expect(result.current.error).toBe('运营数据刷新失败，请稍后重试')
  })

  it('never overlaps an unfinished polling request', async () => {
    renderHook(() => useOperationsSummary())
    await act(async () => { await Promise.resolve() })
    vi.mocked(operationsApi.fetchOperationsSummary).mockReturnValue(new Promise(() => undefined))

    await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000) })

    expect(operationsApi.fetchOperationsSummary).toHaveBeenCalledTimes(2)
  })
})
