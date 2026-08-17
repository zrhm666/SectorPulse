import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchRun } from './api'
import { useRunSSE } from './useRuns'

vi.mock('./api', () => ({ fetchRun: vi.fn() }))

class MockEventSource {
  static instances: MockEventSource[] = []
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor(public readonly url: string) {
    MockEventSource.instances.push(this)
  }

  close = vi.fn()
}

describe('useRunSSE reconnect', () => {
  afterEach(() => {
    vi.clearAllMocks()
    MockEventSource.instances = []
  })

  it('reconnects after a transient error while the run is active', async () => {
    vi.mocked(fetchRun).mockResolvedValue({
      run_id: 'run-2',
      requested_at: '2026-08-17T00:00:00Z',
      provider: 'fixture',
      status: 'RUNNING',
      elapsed_ms: null,
      total_cost_cny: null,
      draft_id: null,
    })
    vi.stubGlobal('EventSource', MockEventSource)

    const { result } = renderHook(() => useRunSSE('run-2'))
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1))

    MockEventSource.instances[0].onerror?.()

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(2), {
      timeout: 2000,
    })
    expect(result.current.done).toBe(false)
  })
})
