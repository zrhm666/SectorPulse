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

  it('does not open SSE for a completed historical run', async () => {
    vi.mocked(fetchRun).mockResolvedValue({
      run_id: 'run-1',
      requested_at: '2026-08-17T00:00:00Z',
      provider: 'fixture',
      status: 'READY_FOR_HUMAN_REVIEW',
      elapsed_ms: 100,
      total_cost_cny: '0',
      draft_id: 'draft-1',
    })
    vi.stubGlobal('EventSource', MockEventSource)

    const { result } = renderHook(() => useRunSSE('run-1'))

    await waitFor(() => expect(result.current.done).toBe(true))
    expect(MockEventSource.instances).toHaveLength(0)
  })
})
