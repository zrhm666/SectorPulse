import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  fetchDataRunContentRun,
  fetchDataRunMarket,
  retryDataRun,
} from './dataRunsApi'


function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}


describe('data run workbench api', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('encodes market kind and pagination', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({
      snapshots: [], kind: 'CONCEPT', items: [], total: 0, offset: 20, limit: 20,
    }))

    await fetchDataRunMarket('run/id', 'CONCEPT', 20, 20)

    expect(fetch).toHaveBeenCalledWith(
      '/api/data-runs/run%2Fid/market?kind=CONCEPT&offset=20&limit=20',
      undefined,
    )
  })

  it('parses an absent content run as null', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(null))

    await expect(fetchDataRunContentRun('run-1')).resolves.toBeNull()
  })

  it('posts retry and returns the new run id', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ run_id: 'run-2' }))

    await expect(retryDataRun('run-1')).resolves.toEqual({ run_id: 'run-2' })
    expect(fetch).toHaveBeenCalledWith('/api/data-runs/run-1/retry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
  })

  it('uses the API detail when a request fails', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'run cannot be retried' }, 409))

    await expect(retryDataRun('run-1')).rejects.toThrow('run cannot be retried')
  })
})
