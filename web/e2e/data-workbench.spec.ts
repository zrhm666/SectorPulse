import type { Page, Route } from '@playwright/test'
import { expect, test } from './fixtures'

type FixtureState = 'ready' | 'active' | 'degraded' | 'empty' | 'stale' | 'failed'

const candidateItems = Array.from({ length: 24 }, (_, index) => ({
  sector_id: `industry-${index + 1}`,
  sector_kind: 'INDUSTRY',
  name: index === 0 ? '机器人' : `候选板块 ${index + 1}`,
  rank: index + 1,
  score: String(100 - index),
  reasons: ['综合评分领先'],
  pct_change: String((3 - index / 10).toFixed(1)),
  turnover_rate: index % 2 ? null : '2.1',
  total_market_cap: null,
  advancers: 20 + index,
  decliners: 5,
  leader_name: '示例股份',
  leader_pct_change: '8.6',
  field_availability: { pct_change: true, turnover_rate: index % 2 === 0 },
  news_count: 12 - (index % 8),
}))

const marketItems = candidateItems.map((item) => ({
  sector_id: item.sector_id,
  name: item.name,
  kind: 'INDUSTRY',
  pct_change: item.pct_change,
  turnover_rate: item.turnover_rate,
  total_market_cap: null,
  advancers: item.advancers,
  decliners: item.decliners,
  leader_name: item.leader_name,
  leader_pct_change: item.leader_pct_change,
  breadth_ratio: '0.80',
  field_availability: {
    pct_change: true, turnover_rate: item.field_availability.turnover_rate,
    advancers: true, decliners: true, leader_name: true, leader_pct_change: true,
  },
}))

const newsItems = Array.from({ length: 22 }, (_, index) => ({
  document_id: `doc-${index + 1}`,
  source_id: index % 2 ? 'eastmoney' : 'cls',
  query_source_id: index % 2 ? 'eastmoney' : 'cls',
  citation_url: index === 1 ? null : `https://example.com/news-${index + 1}`,
  title: index === 0 ? '机器人产业链出现新进展' : `新闻记录 ${index + 1}`,
  publisher: index % 2 ? '东方财富' : '财联社',
  summary: index === 1 ? null : '系统保存的是短摘要，不是新闻原文。',
  published_at: '2026-08-27T08:00:00Z',
  source_observed_at: '2026-08-27T08:01:00Z',
  collected_at: '2026-08-27T08:02:00Z',
  source_grade: 'REPUTABLE_MEDIA',
  query_ids: ['query-1'],
  query_type: 'sector',
  query_status: 'SUCCESS',
}))

function statusFor(state: FixtureState) {
  if (state === 'active') return 'FETCHING_NEWS'
  if (state === 'degraded' || state === 'stale') return 'DEGRADED'
  if (state === 'failed') return 'FAILED'
  return 'READY_FOR_ATTRIBUTION'
}

async function installWorkbenchFixture(page: Page, state: FixtureState = 'ready') {
  let selection = {
    run_id: 'run-e2e', confirmed: true, version: 1,
    selected_sector_ids: ['industry-1', 'industry-2', 'industry-3'],
    method: 'MANUAL', confirmed_at: '2026-08-27T08:03:00Z',
    data_version: 'a'.repeat(64), edit_count: 0,
  }

  const fulfill = (route: Route, json: unknown, status = 200) => route.fulfill({ json, status })
  const handleRoute = async (route: Route) => {
    const request = route.request()
    const url = new URL(request.url())
    const suffix = url.pathname.replace('/api/data-runs/run-e2e', '')
    const status = statusFor(state)

    if (!suffix) {
      return fulfill(route, {
        run_id: 'run-e2e', provider: 'live', mode: 'post_close', status,
        requested_at: '2026-08-27T08:00:00Z', cutoff_at: '2026-08-27T08:01:00Z',
        request: { mode: 'post_close', requested_at: '2026-08-27T08:00:00Z', lookback_hours: 6, precandidate_limit: 30, final_candidate_limit: 12 },
        quality: {}, quality_summary: null,
        downgrade_reasons: state === 'degraded' || state === 'stale' ? ['新闻来源返回历史缓存'] : [],
        error_code: state === 'failed' ? 'PROVIDER_FAILED' : null,
        finished_at: state === 'active' ? null : '2026-08-27T08:03:00Z',
      })
    }
    if (suffix === '/summary') {
      return fulfill(route, {
        run_id: 'run-e2e', status, workflow_stage: status,
        workflow_stage_index: state === 'active' ? 2 : 5,
        terminal: state !== 'active', requested_at: '2026-08-27T08:00:00Z',
        cutoff_at: '2026-08-27T08:01:00Z',
        finished_at: state === 'active' ? null : '2026-08-27T08:03:00Z',
        candidate_count: state === 'empty' ? 0 : candidateItems.length,
      })
    }
    if (suffix === '/selection') {
      if (request.method() === 'PUT') {
        const body = request.postDataJSON() as { sector_ids: string[]; expected_version: number }
        selection = { ...selection, version: body.expected_version + 1, selected_sector_ids: body.sector_ids, edit_count: selection.edit_count + 1 }
      }
      return fulfill(route, state === 'empty' ? { ...selection, confirmed: false, version: 0, selected_sector_ids: [], method: null, confirmed_at: null } : selection)
    }
    if (suffix === '/content-run') return fulfill(route, null)
    if (suffix === '/acquisition') {
      return fulfill(route, {
        market_sources: state === 'empty' ? [] : [{ kind: 'INDUSTRY', provider_id: 'akshare-ths', classification_version: '2026.08', source_version: 'v2', observed_at: '2026-08-27T08:01:00Z', collected_at: '2026-08-27T08:02:00Z', sector_count: marketItems.length, available_fields: ['pct_change', 'turnover_rate'], raw_artifact_sha256: 'b'.repeat(64) }],
        news_sources: state === 'empty' ? [] : [{ source_id: 'eastmoney', status: state === 'stale' ? 'STALE' : 'SUCCESS', query_count: 2, status_counts: { SUCCESS: 2, EMPTY: 0, PARTIAL: 0, STALE: 0, UNAVAILABLE: 0, FAILED: 0 }, result_count: newsItems.length, call_count: 2, retry_count: 0, duration_ms: 230, error_codes: [] }],
        counts: state === 'empty' ? { provider_results: 0, normalized_documents: 0, evidence_events: 0 } : { provider_results: 24, normalized_documents: 22, evidence_events: 10 },
        coverage: state === 'stale' ? 'LINKED_ONLY' : 'COMPLETE',
        coverage_notice: state === 'stale' ? '当前仅能展示历史关联记录。' : null,
      })
    }
    if (suffix === '/candidates') {
      const query = (url.searchParams.get('query') ?? '').toLowerCase()
      const sort = url.searchParams.get('sort') ?? 'rank'
      const direction = url.searchParams.get('direction') ?? 'asc'
      const offset = Number(url.searchParams.get('offset') ?? 0)
      const limit = Number(url.searchParams.get('limit') ?? 20)
      let items = state === 'empty' ? [] : candidateItems.filter((item) => `${item.name}${item.sector_id}`.toLowerCase().includes(query))
      items = [...items].sort((left, right) => {
        const a = sort === 'name' ? left.name : Number(left[sort as 'rank' | 'score' | 'pct_change' | 'news_count'])
        const b = sort === 'name' ? right.name : Number(right[sort as 'rank' | 'score' | 'pct_change' | 'news_count'])
        const compared = typeof a === 'string' ? a.localeCompare(String(b), 'zh-CN') : a - Number(b)
        return direction === 'desc' ? -compared : compared
      })
      return fulfill(route, { items: items.slice(offset, offset + limit), total: items.length, offset, limit, query: query || null, sort, direction, data_version: 'a'.repeat(64) })
    }
    if (suffix === '/market') {
      const offset = Number(url.searchParams.get('offset') ?? 0)
      const limit = Number(url.searchParams.get('limit') ?? 20)
      const items = state === 'empty' ? [] : marketItems
      return fulfill(route, { snapshots: state === 'empty' ? [] : [{ kind: 'INDUSTRY', provider_id: 'akshare-ths', classification_version: '2026.08', source_version: 'v2', observed_at: '2026-08-27T08:01:00Z', collected_at: '2026-08-27T08:02:00Z', sector_count: items.length, available_fields: ['pct_change', 'turnover_rate'], raw_artifact_sha256: 'b'.repeat(64) }], kind: 'INDUSTRY', items: items.slice(offset, offset + limit), total: items.length, offset, limit })
    }
    if (suffix === '/news-records') {
      const offset = Number(url.searchParams.get('offset') ?? 0)
      const limit = Number(url.searchParams.get('limit') ?? 20)
      const source = url.searchParams.get('source_id')
      const items = (state === 'empty' ? [] : newsItems).filter((item) => !source || item.query_source_id === source)
      return fulfill(route, { items: items.slice(offset, offset + limit), total: items.length, offset, limit, coverage: state === 'stale' ? 'LINKED_ONLY' : 'COMPLETE', coverage_notice: state === 'stale' ? '当前仅能展示历史关联记录。' : null })
    }
    if (suffix.startsWith('/news-records/')) {
      const id = suffix.split('/').at(-1)!
      const item = newsItems.find((entry) => entry.document_id === id) ?? newsItems[0]
      const linkOnly = id === 'doc-2'
      return fulfill(route, { ...item, citation_url: linkOnly ? null : item.citation_url, content_kind: linkOnly ? 'LINK_ONLY' : 'SUMMARY', content: linkOnly ? null : item.summary, content_available: !linkOnly })
    }
    if (suffix === '/evidence') return fulfill(route, { events: [], total: 0 })
    if (suffix === '/quality') return fulfill(route, { market_quality: { industry: state === 'degraded' ? 'DEGRADED' : 'NORMAL' }, news_quality: { news: state === 'stale' ? 'STALE' : 'NORMAL' }, cutoff_violation_count: 0, duplicate_document_count: 0, downgrade_reasons: [], error_code: null })
    if (suffix === '/generate') return fulfill(route, { run_id: 'content-e2e' })
    if (suffix === '/retry') return fulfill(route, { run_id: 'retry-e2e' })
    return route.fallback()
  }
  await page.route('**/api/data-runs/run-e2e', handleRoute)
  await page.route('**/api/data-runs/run-e2e/**', handleRoute)
}

async function openWorkbench(page: Page, viewport: { width: number; height: number }, state: FixtureState = 'ready') {
  await installWorkbenchFixture(page, state)
  await page.setViewportSize(viewport)
  await page.goto('/data-runs/run-e2e')
  await expect(page.getByRole('region', { name: '数据运行摘要' })).toBeVisible()
}

for (const viewport of [{ width: 1536, height: 1024 }, { width: 1440, height: 900 }]) {
  test(`desktop workbench preserves hierarchy at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await openWorkbench(page, viewport)
    await expect(page.getByRole('heading', { name: '盘后数据运行' })).toBeVisible()
    await expect(page.getByRole('tablist', { name: '数据运行详情' })).toBeVisible()
    await expect(page.getByText('数据处理进度')).toBeHidden()
    await page.getByText('处理与采集详情', { exact: true }).click()
    await expect(page.getByText('数据处理进度')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })
}

for (const width of [1440, 1024, 390]) {
  test(`results-first data layout at ${width}`, async ({ page }) => {
    await openWorkbench(page, { width, height: 900 })
    await expect(page.locator('.data-processing-details')).not.toHaveAttribute('open')
    const market = page.getByRole('tab', { name: '行情板块' })
    await market.focus()
    await page.keyboard.press('ArrowRight')
    await expect(page.getByRole('tab', { name: '候选板块' })).toBeFocused()
    await expect(page.getByRole('tab', { name: '候选板块' })).toHaveAttribute('aria-selected', 'true')
    await page.getByRole('tab', { name: '行情板块' }).click()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: test.info().outputPath(`data-${width}.png`) })
  })
}

test('candidate search, sort, pagination and immutable confirmation stay truthful', async ({ page }) => {
  await openWorkbench(page, { width: 1440, height: 900 })
  await page.getByRole('tab', { name: '候选板块' }).click()
  await expect(page.getByText('已选择 3 个')).toBeVisible()
  await page.getByRole('searchbox', { name: '搜索候选板块' }).fill('机器人')
  await expect(page.getByRole('cell', { name: '机器人 industry-1' })).toBeVisible()
  await page.getByRole('searchbox', { name: '搜索候选板块' }).fill('')
  await page.getByLabel('候选排序').selectOption('news_count')
  await page.getByRole('button', { name: '降序' }).click()
  await page.getByRole('checkbox', { name: '选择候选板块 4' }).check()
  await expect(page.getByRole('button', { name: '生成分析稿' })).toBeDisabled()
  await page.getByRole('button', { name: '确认 4 个板块' }).click()
  await expect(page.getByText('已确认 v2')).toBeVisible()
  await expect(page.getByRole('button', { name: '生成分析稿' })).toBeEnabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('market and news drawers expose provenance without inventing full text', async ({ page }) => {
  await openWorkbench(page, { width: 1024, height: 768 })
  await page.getByRole('button', { name: '查看详情' }).first().click()
  await expect(page.getByRole('dialog', { name: /行情详情/ })).toContainText('采集血缘')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toBeHidden()

  await page.getByRole('tab', { name: '新闻记录' }).click()
  await page.getByRole('button', { name: '查看已保存详情' }).first().click()
  const summaryDrawer = page.getByRole('dialog')
  await expect(summaryDrawer.locator('.content-kind-badge')).toHaveAttribute('data-kind', 'SUMMARY')
  await expect(summaryDrawer).toContainText('系统未保存新闻全文')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '查看已保存详情' }).nth(1).click()
  const linkOnlyDrawer = page.getByRole('dialog')
  await expect(linkOnlyDrawer.locator('.content-kind-badge')).toHaveAttribute('data-kind', 'LINK_ONLY')
  await expect(linkOnlyDrawer.getByRole('link', { name: '打开安全原文链接' })).toHaveCount(0)
})

test('mobile drawer is reachable and the page has no root overflow', async ({ page }) => {
  await openWorkbench(page, { width: 390, height: 844 })
  await page.getByRole('button', { name: '查看详情' }).first().click()
  const drawer = page.getByRole('dialog', { name: /行情详情/ })
  await expect(drawer).toBeVisible()
  const box = await drawer.boundingBox()
  expect(box?.width).toBeGreaterThanOrEqual(388)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: '查看详情' }).first()).toBeFocused()
})

for (const state of ['active', 'degraded', 'empty', 'stale', 'failed'] as const) {
  test(`${state} fixture remains distinguishable and usable`, async ({ page }) => {
    await openWorkbench(page, { width: 768, height: 1024 }, state)
    if (state === 'active') await expect(page.getByText('进行中').first()).toBeVisible()
    if (state === 'degraded' || state === 'stale') await expect(page.getByText('本次运行存在数据降级')).toBeVisible()
    if (state === 'empty') await expect(page.getByText('行情板块尚未产生，当前运行可能仍在采集阶段。')).toBeVisible()
    if (state === 'failed') await expect(page.getByRole('button', { name: '按原参数重新采集' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })
}
