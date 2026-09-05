import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchRun } from './api'
import { useRunSSE } from './useRuns'

vi.mock('./api', () => ({
  fetchRun: vi.fn(),
}))

class MockEventSource {
  static instances: MockEventSource[] = []
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor(public readonly url: string) {
    MockEventSource.instances.push(this)
  }

  close = vi.fn()
}

describe('useRunSSE', () => {
  afterEach(() => {
    vi.clearAllMocks()
    MockEventSource.instances = []
  })

  it.each(['READY_FOR_HUMAN_REVIEW', 'INTERRUPTED', 'UNREVIEWED', 'REVISE_REQUIRED'])('does not open SSE for historical %s', async (status) => {
    vi.mocked(fetchRun).mockResolvedValue({
      run_id: 'run-1',
      requested_at: '2026-08-17T00:00:00Z',
      provider: 'fixture',
      status,
      elapsed_ms: 100,
      total_cost_cny: '0',
      draft_id: 'draft-1',
    })
    vi.stubGlobal('EventSource', MockEventSource)

    const { result } = renderHook(() => useRunSSE('run-1'))

    await waitFor(() => expect(result.current.done).toBe(true))
    expect(MockEventSource.instances).toHaveLength(0)
  })

  it('clears completed state when navigating to a running task', async () => {
    vi.mocked(fetchRun).mockResolvedValueOnce({ run_id: 'old', status: 'READY_FOR_HUMAN_REVIEW' } as Awaited<ReturnType<typeof fetchRun>>)
      .mockResolvedValue({ run_id: 'new', status: 'RUNNING' } as Awaited<ReturnType<typeof fetchRun>>)
    vi.stubGlobal('EventSource', MockEventSource)
    const { result, rerender } = renderHook(({ id }) => useRunSSE(id), { initialProps: { id: 'old' } })
    await waitFor(() => expect(result.current.done).toBe(true))
    rerender({ id: 'new' })
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1))
    expect(result.current.done).toBe(false)
    expect(result.current.events).toEqual([])
  })
})
