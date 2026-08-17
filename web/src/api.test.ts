import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchFixtureInput, retryRun } from './api'

describe('retryRun', () => {
  afterEach(() => vi.restoreAllMocks())

  it('posts the run id and returns the new run id', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ run_id: 'next-run' }), { status: 200 }),
    ))

    await expect(retryRun('old-run')).resolves.toEqual({ run_id: 'next-run' })
    expect(fetch).toHaveBeenCalledWith('/api/runs/old-run/retry', { method: 'POST' })
  })
})

describe('fetchFixtureInput', () => {
  afterEach(() => vi.restoreAllMocks())

  it('loads the built-in example input', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ contexts: [], gates: {} }), { status: 200 }),
    ))
    await expect(fetchFixtureInput()).resolves.toEqual({ contexts: [], gates: {} })
    expect(fetch).toHaveBeenCalledWith('/api/fixture-input')
  })
})
