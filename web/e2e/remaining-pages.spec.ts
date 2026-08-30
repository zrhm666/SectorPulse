import type { Page, Route } from '@playwright/test'
import { expect, test } from './fixtures'

const now = '2026-08-28T10:00:00Z'
const contentRun = (runId = 'content-run') => ({
  run_id: runId, requested_at: now, provider: 'fixture', status: 'READY_FOR_HUMAN_REVIEW',
  elapsed_ms: 1200, total_cost_cny: '0', draft_id: 'draft-1', sector_count: 8, retryable: true,
})
const failedRun = {
  run_id: 'failed-run', requested_at: '2026-06-01T10:00:00Z', provider: 'live', status: 'FAILED',
  elapsed_ms: 60000, total_cost_cny: '1.2', draft_id: null, error_message: '上游服务暂时不可用', retryable: true,
}
const operationsSummary = {
  database: { backend: 'postgresql', name: 'sector_pulse' },
  llm: { provider: 'openai-compatible', model: 'safe-model', budget_cny_per_run: '2', configured: true },
  consent: { live_data: true, live_llm: true },
  providers: { live_data_available: true, missing_requirements: [] },
  runs: { total: 2, running: 0, awaiting_review: 1, failed: 1, recent: [] },
  summary: { total: 2, completed_today: 1, active: 0, attention: 1 },
  trend: { available: false, reason: '样本不足', points: [] },
  readiness: {
    database: { status: 'ready', label: '数据库', detail: 'PostgreSQL 已连接', detail_path: '/system' },
    live_data: { status: 'ready', label: '实时数据', detail: 'Provider 与授权已就绪', detail_path: '/system' },
    llm: { status: 'ready', label: 'LLM', detail: '模型配置已就绪', detail_path: '/system' },
    scheduler: { status: 'disabled', label: '调度器', detail: '当前配置为停用', detail_path: '/system' },
  },
  recent_runs: [], generated_at: now,
}

async function installFixture(page: Page) {
  const state = { createdSchedules: 0, retries: 0 }

  const fulfill = (route: Route, json: unknown, status = 200) => route.fulfill({ json, status })
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    if (path === '/api/runs' && method === 'GET') return fulfill(route, [contentRun(), failedRun])
    if (path === '/api/runs' && method === 'POST') return fulfill(route, { run_id: 'fixture-created' }, 201)
    if (path === '/api/data-runs') return fulfill(route, [{ run_id: 'data-run', mode: 'post_close', status: 'READY_FOR_ATTRIBUTION', requested_at: now, quality: {}, downgrade_reasons: [] }])
    if (path === '/api/operations/summary') return fulfill(route, operationsSummary)
    if (path === '/api/fixture-input') return fulfill(route, { requested_at: now, sectors: [] })
    if (/^\/api\/runs\/[^/]+\/retry$/.test(path) && method === 'POST') { state.retries += 1; return fulfill(route, { run_id: 'retried-run' }, 201) }
    if (/^\/api\/runs\/[^/]+\/evidence$/.test(path)) return fulfill(route, { sectors: [], events: [], invocations: [] })
    if (/^\/api\/runs\/[^/]+$/.test(path)) return fulfill(route, contentRun(path.split('/').at(-1)))
    if (path === '/api/schedules' && method === 'GET') return fulfill(route, [{ schedule_id: 'schedule-1', name: '盘后计划', mode: 'post_close', timezone: 'Asia/Shanghai', local_time: '16:00', trading_days: 'weekdays', enabled: true, next_run_at: null }])
    if (path === '/api/schedules' && method === 'POST') { state.createdSchedules += 1; return fulfill(route, { schedule_id: 'schedule-2', ...request.postDataJSON(), next_run_at: null }, 201) }
    if (path === '/api/schedules/schedule-1/trigger' && method === 'POST') return fulfill(route, { run_id: 'task-run' }, 201)
    if (path === '/api/task-runs/task-run') return fulfill(route, { run_id: 'task-run', status: 'COMPLETED', provider: 'fixture', input_fingerprint: 'fingerprint', stages: [{ stage: 'FETCHING_MARKET', attempt_no: 1, status: 'COMPLETED', error_code: null }], events: [{ event_type: 'TASK_COMPLETED', summary: '任务已完成', created_at: now }], downgrade_reasons: [] })
    if (path === '/api/shadow-runs/summary') return fulfill(route, { trading_days: 1, passed: 1, failed: 0, blocked: 0, remaining: 19, complete: false })
    if (path === '/api/shadow-runs') return fulfill(route, [{ shadow_id: 'shadow-1', run_id: 'content-run', trading_date: '2026-08-28', mode: 'post_close', status: 'PASSED', created_at: now }])
    return route.fallback()
  })
  return state
}

const responsivePages = [
  ['/runs', '分析运行'], ['/runs/new', '新建分析'], ['/runs/content-run', '内容运行 content-'],
  ['/schedules', '定时任务'], ['/task-runs/task-run', '任务 task-run'], ['/system', '系统状态'], ['/shadow-acceptance', '影子验收'],
] as const

for (const viewport of [{ width: 1536, height: 1024 }, { width: 1440, height: 900 }, { width: 1280, height: 800 }, { width: 1024, height: 768 }, { width: 768, height: 1024 }, { width: 390, height: 844 }]) {
  test(`remaining pages have no root overflow at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await installFixture(page)
    await page.setViewportSize(viewport)
    for (const [path, heading] of responsivePages) {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    }
  })
}

test('run registry filters truthful records and discloses stored errors', async ({ page }) => {
  await installFixture(page)
  await page.goto('/runs')
  await page.getByLabel('按场景筛选').selectOption('post_close')
  await expect(page.getByTitle('data-run')).toBeVisible()
  await page.getByRole('button', { name: '重置筛选' }).click()
  await page.getByTitle('failed-run').locator('xpath=ancestor::tr').getByRole('button', { name: '查看错误详情' }).click()
  await expect(page.getByText('上游服务暂时不可用')).toBeVisible()
})

test('four-step launcher preserves truthful fixture behavior and prevents duplicate creation', async ({ page }) => {
  await installFixture(page)
  await page.goto('/runs/new')
  await page.getByRole('button', { name: /盘后复盘/ }).click()
  await page.getByRole('button', { name: '下一步：选择执行方式' }).click()
  await page.getByRole('button', { name: /Fixture 演练/ }).click()
  await page.getByRole('button', { name: '下一步：确认参数' }).click()
  await page.getByRole('button', { name: '下一步：启动' }).click()
  const createRequest = page.waitForRequest((request) => request.url().endsWith('/api/runs') && request.method() === 'POST')
  await page.getByRole('button', { name: '启动 Fixture 分析' }).click()
  await createRequest
  await expect(page).toHaveURL(/\/runs\/fixture-created$/)
})

test('content workspace keeps tabs, evidence, review link and retry attached to real APIs', async ({ page }) => {
  const state = await installFixture(page)
  await page.goto('/runs/content-run')
  await expect(page.getByRole('region', { name: '运行阶段' })).toBeVisible()
  await page.getByRole('tab', { name: '证据' }).click()
  await expect(page.getByRole('tabpanel', { name: '证据' })).toBeVisible()
  await expect(page.getByRole('link', { name: '进入审核工作台' })).toHaveAttribute('href', '/review?run=content-run')
  await page.getByRole('button', { name: '重新运行' }).click()
  await expect.poll(() => state.retries).toBe(1)
  await expect(page).toHaveURL(/\/runs\/retried-run$/)
})

test('schedule drawer, task history, system safety and shadow history stay operational', async ({ page }) => {
  const state = await installFixture(page)
  await page.goto('/schedules')
  const trigger = page.getByRole('button', { name: '新建计划' })
  await trigger.click()
  await expect(page.getByLabel('计划名称')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
  await trigger.click()
  await page.getByLabel('计划名称').fill('盘中计划')
  await page.getByRole('button', { name: '保存计划' }).click()
  await expect.poll(() => state.createdSchedules).toBe(1)
  await page.getByRole('button', { name: '立即运行' }).first().click()
  await expect(page).toHaveURL(/\/task-runs\/task-run$/)
  await expect(page.getByText('任务已完成')).toBeVisible()
  await expect(page.getByRole('button', { name: '重试' })).toHaveCount(0)
  await page.goto('/system')
  await expect(page.getByText(/检查时间/)).toBeVisible()
  await expect(page.getByText(/api[_ -]?key/i)).toHaveCount(0)
  await page.goto('/shadow-acceptance')
  await expect(page.getByRole('table', { name: '影子运行历史' })).toBeVisible()
  await expect(page.getByRole('button')).toHaveCount(0)
})
