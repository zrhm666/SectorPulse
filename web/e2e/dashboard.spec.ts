import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

const summary = {
  database: { backend: 'postgresql', name: 'sectorpulse' },
  llm: { provider: 'openai-compatible', model: 'model-a', budget_cny_per_run: '2.00', configured: true },
  consent: { live_data: true, live_llm: true },
  providers: { live_data_available: true, missing_requirements: [] },
  runs: { total: 12, running: 2, awaiting_review: 1, failed: 1, recent: [] },
  summary: { total: 12, completed_today: 3, active: 2, attention: 2 },
  trend: {
    available: true,
    reason: null,
    points: [
      { date: '2026-08-24', total: 2, completed: 1, failed: 0 },
      { date: '2026-08-25', total: 4, completed: 3, failed: 1 },
      { date: '2026-08-26', total: 3, completed: 2, failed: 0 },
      { date: '2026-08-27', total: 3, completed: 1, failed: 1 },
    ],
  },
  readiness: {
    database: { status: 'ready', label: '数据库', detail: 'PostgreSQL 已连接', detail_path: '/system' },
    live_data: { status: 'ready', label: '实时数据', detail: 'Provider 与授权已就绪', detail_path: '/system' },
    llm: { status: 'warning', label: 'LLM', detail: '等待实时 LLM 授权', detail_path: '/system' },
    scheduler: { status: 'disabled', label: '调度器', detail: '当前配置为停用', detail_path: '/system' },
  },
  recent_runs: [
    { run_id: 'content-00000001', kind: 'content', mode: '内容生成', status: 'READY_FOR_HUMAN_REVIEW', provider: 'live', requested_at: '2026-08-27T09:00:00+08:00', finished_at: '2026-08-27T09:01:00+08:00', elapsed_ms: 60_000, total_cost_cny: '0.2', candidate_count: 3, detail_path: '/runs/content-00000001' },
    { run_id: 'data-00000000001', kind: 'data', mode: '盘后复盘', status: 'FETCHING_NEWS', provider: 'live', requested_at: '2026-08-27T10:00:00+08:00', finished_at: null, elapsed_ms: null, total_cost_cny: null, candidate_count: null, detail_path: '/data-runs/data-00000000001' },
  ],
  generated_at: '2026-08-27T12:00:00+00:00',
}

async function openDashboard(page: Page, width: number, height: number) {
  await page.route('**/api/operations/summary', (route) => route.fulfill({ json: summary }))
  await page.setViewportSize({ width, height })
  await page.goto('/')
  await expect(page.getByRole('region', { name: '核心运营指标' })).toBeVisible()
}

for (const viewport of [{ width: 1536, height: 1024 }, { width: 1440, height: 900 }]) {
  test(`desktop dashboard uses the balanced grid at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await openDashboard(page, viewport.width, viewport.height)

    await expect(page.getByRole('article')).toHaveCount(4)
    const trend = await page.getByRole('region', { name: '运行趋势' }).boundingBox()
    const readiness = await page.getByRole('region', { name: '系统就绪状态' }).boundingBox()
    expect(Math.abs((trend?.y ?? 0) - (readiness?.y ?? 1))).toBeLessThan(2)
    expect((trend?.width ?? 0) / (readiness?.width ?? 1)).toBeGreaterThan(1.7)
    await expect(page.getByRole('region', { name: '最近运行' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })
}

test('tablet stacks trend and readiness without page overflow', async ({ page }) => {
  await openDashboard(page, 1024, 768)
  const trend = await page.getByRole('region', { name: '运行趋势' }).boundingBox()
  const readiness = await page.getByRole('region', { name: '系统就绪状态' }).boundingBox()
  expect((readiness?.y ?? 0)).toBeGreaterThan((trend?.y ?? 0) + (trend?.height ?? 0) - 2)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('mobile keeps controls reachable and confines wide content to the table viewport', async ({ page }) => {
  await openDashboard(page, 390, 844)

  await expect(page.getByRole('button', { name: '刷新状态' })).toBeVisible()
  await expect(page.getByRole('link', { name: '新建分析' })).toBeVisible()
  await expect(page.getByRole('button', { name: '近 7 天' })).toBeVisible()
  const tableViewport = page.locator('.operations-recent__viewport')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(await tableViewport.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true)
})
