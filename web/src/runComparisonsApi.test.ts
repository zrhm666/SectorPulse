import { afterEach, expect, it, vi } from 'vitest'
import { fetchComparisonRuns, fetchRunComparison, fetchComparisonNews, fetchComparisonEvidence } from './runComparisonsApi'
import { pair } from './testComparisonFixtures'

afterEach(() => vi.unstubAllGlobals())
it('uses four relative GET endpoints with encoded filters and cancellation', async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
  vi.stubGlobal('fetch', fetcher)
  const signal = new AbortController().signal
  await fetchComparisonRuns({ provider: 'fixture', mode: 'post_close', offset: 40, limit: 20 }, signal)
  await fetchRunComparison(pair, signal)
  await fetchComparisonNews(pair, { membership: 'BOTH', offset: 20, limit: 20 }, signal)
  await fetchComparisonEvidence(pair, { kind: 'CONCEPT', sector_id: 'a&b', offset: 0, limit: 20 }, signal)
  expect(fetcher.mock.calls.map(([url]) => url.split('?')[0])).toEqual([
    '/api/run-comparisons/runs', '/api/run-comparisons', '/api/run-comparisons/news', '/api/run-comparisons/evidence',
  ])
  for (const [, options] of fetcher.mock.calls) expect(options).toEqual({ signal })
  expect(fetcher.mock.calls[3][0]).toContain('sector_id=a%26b')
})
it.each([404, 409, 422, 500])('reports %s instead of returning an empty success', async (status) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status, json: async () => ({ error: { message: '所选运行不可比较' } }) }))
  await expect(fetchRunComparison(pair, new AbortController().signal)).rejects.toThrow('所选运行不可比较')
})
