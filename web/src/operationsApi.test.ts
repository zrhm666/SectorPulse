import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchOperationsSummary } from './operationsApi'

describe('fetchOperationsSummary', () => {
  afterEach(() => vi.restoreAllMocks())

  it('loads the redacted operations summary', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ database: { backend: 'postgresql', name: 'runtime' } }), { status: 200 }),
    ))

    await expect(fetchOperationsSummary()).resolves.toMatchObject({
      database: { backend: 'postgresql', name: 'runtime' },
    })
    expect(fetch).toHaveBeenCalledWith('/api/operations/summary')
  })

  it('rejects an unsuccessful response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })))

    await expect(fetchOperationsSummary()).rejects.toThrow('operations summary failed: 503')
  })
})
