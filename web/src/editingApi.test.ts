import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyDraftPatch, fetchGovernance } from './editingApi'

afterEach(() => vi.restoreAllMocks())

describe('review API errors', () => {
  it('classifies a version conflict without exposing an upstream body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'draft version conflict' }),
      { status: 409, headers: { 'Content-Type': 'application/json' } },
    )))

    const request = applyDraftPatch('run-1', 'draft-1', {
      base_version: 1, path: 'introduction', old_value_hash: 'a', value: 'new',
    })

    await expect(request).rejects.toMatchObject({
      status: 409, code: 'CONFLICT', message: 'draft version conflict',
    })
  })

  it('uses a safe local message when a proxy returns HTML', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>gateway</html>', { status: 503 })))

    await expect(fetchGovernance('run-1')).rejects.toMatchObject({
      status: 503, code: 'UNAVAILABLE', message: '审核请求未完成，请稍后重试。',
    })
  })

  it('passes cancellation through read requests', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ status: 'PASS', issues: [] }), { status: 200 },
    )))
    const controller = new AbortController()

    await fetchGovernance('run-1', controller.signal)

    expect(fetch).toHaveBeenCalledWith('/api/runs/run-1/governance', { signal: controller.signal })
  })
})
