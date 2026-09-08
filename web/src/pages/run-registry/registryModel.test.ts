import { expect, it } from 'vitest'
import { registryRows, selectRegistry, registryReturnTo } from './registryModel'

const now = Date.parse('2026-09-08T08:00:00Z')
const rows = registryRows(Array.from({ length: 45 }, (_, i) => ({ run_id: `Run-${i}`, requested_at: new Date(now - i * 1000).toISOString(), provider: 'live', status: 'FAILED', elapsed_ms: null, total_cost_cny: null, draft_id: null })), [])

it('filters case-insensitively before pagination and bounds page numbers', () => {
  expect(selectRegistry(rows, new URLSearchParams('page=3'), now).items).toHaveLength(5)
  expect(selectRegistry(rows, new URLSearchParams('page=-2'), now).page).toBe(1)
  expect(selectRegistry(rows, new URLSearchParams('page=abc'), now).page).toBe(1)
  expect(selectRegistry(rows, new URLSearchParams('page=999'), now).page).toBe(3)
  expect(selectRegistry(rows, new URLSearchParams('q=RUN-44&page=3'), now).items.map(row => row.id)).toEqual(['Run-44'])
  expect(selectRegistry(rows, new URLSearchParams('order=asc'), now).items[0].id).toBe('Run-44')
})

it('matches collecting states as active and preserves source separately from scene', () => {
  const data = registryRows([], [{ run_id: 'data-1', provider: 'live', mode: 'post_close', status: 'FETCHING_MARKET', requested_at: new Date(now).toISOString(), quality: {}, downgrade_reasons: [] }])
  expect(selectRegistry(data, new URLSearchParams('status=RUNNING&provider=live&q=盘后'), now).total).toBe(1)
  expect(selectRegistry(data, new URLSearchParams('provider=fixture'), now).total).toBe(0)
})

it('allows only local registry return destinations', () => {
  expect(registryReturnTo({ registryReturnTo: '/runs?q=abc&page=2' })).toBe('/runs?q=abc&page=2')
  for (const value of ['https://evil.test/runs', '//evil.test', '/runs/123', '/runs\\evil', '/runs?x=\n']) {
    expect(registryReturnTo({ registryReturnTo: value })).toBe('/runs')
  }
  expect(registryReturnTo(null)).toBe('/runs')
})
