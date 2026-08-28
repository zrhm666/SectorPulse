import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../dataRunsApi'
import useDataRunWorkbench, { useLatestResource } from './useDataRunWorkbench'

vi.mock('../dataRunsApi', async () => {
  const actual = await vi.importActual<typeof import('../dataRunsApi')>('../dataRunsApi')
  return {
    ...actual,
    fetchDataRun: vi.fn(),
    fetchDataRunSummary: vi.fn(),
    fetchDataRunSelection: vi.fn(),
    fetchDataRunCandidatePage: vi.fn(),
    fetchDataRunContentRun: vi.fn(),
  }
})

const activeRun = {
  run_id: 'run-1', provider: 'fixture' as const, mode: 'post_close' as const,
  status: 'FETCHING_NEWS', requested_at: '2026-08-28T08:00:00Z',
  quality: {}, downgrade_reasons: [],
}
const activeSummary = {
  run_id: 'run-1', status: 'FETCHING_NEWS', workflow_stage: 'NEWS_COLLECTION',
  workflow_stage_index: 3, terminal: false, requested_at: activeRun.requested_at,
  cutoff_at: null, finished_at: null, candidate_count: 3,
}
const selection = {
  run_id: 'run-1', confirmed: false, version: 0, selected_sector_ids: ['a', 'b', 'c'],
  method: null, confirmed_at: null, data_version: 'a'.repeat(64), edit_count: 0,
}
const candidates = {
  items: [], total: 0, offset: 0, limit: 20, query: null,
  sort: 'rank' as const, direction: 'asc' as const, data_version: 'a'.repeat(64),
}

function resolveCore(overrides: { terminal?: boolean; contentStatus?: string | null } = {}) {
  vi.mocked(api.fetchDataRun).mockResolvedValue({
    ...activeRun,
    status: overrides.terminal ? 'READY_FOR_ATTRIBUTION' : activeRun.status,
  })
  vi.mocked(api.fetchDataRunSummary).mockResolvedValue({
    ...activeSummary,
    status: overrides.terminal ? 'READY_FOR_ATTRIBUTION' : activeSummary.status,
    terminal: overrides.terminal ?? false,
  })
  vi.mocked(api.fetchDataRunSelection).mockResolvedValue(selection)
  vi.mocked(api.fetchDataRunCandidatePage).mockResolvedValue(candidates)
  vi.mocked(api.fetchDataRunContentRun).mockResolvedValue(
    overrides.contentStatus
      ? {
          run_id: 'run-1', status: overrides.contentStatus, draft_id: null,
          can_view_draft: false, requested_at: activeRun.requested_at, finished_at: null,
        }
      : null,
  )
}

describe('useDataRunWorkbench', () => {
  let visibility: DocumentVisibilityState

  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    visibility = 'visible'
    vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility)
    resolveCore()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('loads the persisted workbench state on mount', async () => {
    const { result } = renderHook(() => useDataRunWorkbench('run-1'))

    await act(async () => { await Promise.resolve() })

    expect(result.current.initialLoading).toBe(false)
    expect(result.current.run?.status).toBe('FETCHING_NEWS')
    expect(result.current.selection?.version).toBe(0)
    expect(result.current.candidates?.data_version).toBe('a'.repeat(64))
    expect(result.current.stale).toBe(false)
  })

  it('polls every two seconds and stops when both workflows are terminal', async () => {
    renderHook(() => useDataRunWorkbench('run-1'))
    await act(async () => { await Promise.resolve() })

    resolveCore({ terminal: true })
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000) })
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })

    expect(api.fetchDataRun).toHaveBeenCalledTimes(2)
    expect(api.fetchDataRunContentRun).toHaveBeenCalledTimes(2)
  })

  it('keeps polling while a linked content run is active', async () => {
    resolveCore({ terminal: true, contentStatus: 'RUNNING' })
    renderHook(() => useDataRunWorkbench('run-1'))
    await act(async () => { await Promise.resolve() })

    resolveCore({ terminal: true, contentStatus: 'READY_FOR_HUMAN_REVIEW' })
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000) })
    await act(async () => { await vi.advanceTimersByTimeAsync(6_000) })

    expect(api.fetchDataRun).toHaveBeenCalledTimes(2)
  })

  it('pauses polling while the document is hidden', async () => {
    renderHook(() => useDataRunWorkbench('run-1'))
    await act(async () => { await Promise.resolve() })

    visibility = 'hidden'
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })

    expect(api.fetchDataRun).toHaveBeenCalledTimes(1)
  })

  it('never overlaps an unfinished polling request', async () => {
    renderHook(() => useDataRunWorkbench('run-1'))
    await act(async () => { await Promise.resolve() })
    vi.mocked(api.fetchDataRun).mockReturnValue(new Promise(() => undefined))

    await act(async () => { await vi.advanceTimersByTimeAsync(2_000) })
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })

    expect(api.fetchDataRun).toHaveBeenCalledTimes(2)
  })

  it('retains stale data and retries with exponential backoff', async () => {
    const { result } = renderHook(() => useDataRunWorkbench('run-1'))
    await act(async () => { await Promise.resolve() })
    vi.mocked(api.fetchDataRun).mockRejectedValueOnce(new Error('offline'))

    await act(async () => { await vi.advanceTimersByTimeAsync(2_000) })
    expect(result.current.run).not.toBeNull()
    expect(result.current.stale).toBe(true)
    expect(result.current.error).toBe('工作台刷新失败，正在保留最近一次成功数据')

    await act(async () => { await vi.advanceTimersByTimeAsync(3_999) })
    expect(api.fetchDataRun).toHaveBeenCalledTimes(2)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(api.fetchDataRun).toHaveBeenCalledTimes(3)
  })

  it('supports a manual refresh without starting a second request', async () => {
    const { result } = renderHook(() => useDataRunWorkbench('run-1'))
    await act(async () => { await Promise.resolve() })

    await act(async () => {
      await Promise.all([result.current.refresh(), result.current.refresh()])
    })

    expect(api.fetchDataRun).toHaveBeenCalledTimes(2)
  })
})

describe('useLatestResource', () => {
  it('is lazy and prevents an older response from replacing a newer filter', async () => {
    let resolveFirst: ((value: string) => void) | undefined
    const loader = vi.fn((value: string, _signal: AbortSignal) => {
      if (value === 'first') {
        return new Promise<string>((resolve) => { resolveFirst = resolve })
      }
      return Promise.resolve('second-result')
    })
    const { result } = renderHook(() => useLatestResource(loader, '加载失败'))
    expect(loader).not.toHaveBeenCalled()

    act(() => { void result.current.load('first') })
    await act(async () => { await result.current.load('second') })
    expect(result.current.data).toBe('second-result')

    await act(async () => { resolveFirst?.('first-result'); await Promise.resolve() })
    expect(result.current.data).toBe('second-result')
    expect(loader.mock.calls[0][1].aborted).toBe(true)
  })
})
