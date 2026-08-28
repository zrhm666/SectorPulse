import { expect, test, type Page, type Route } from '@playwright/test'

type FixtureMode = 'pending' | 'loading' | 'empty' | 'approved' | 'blocked' | 'failed' | 'conflict'

const browserErrors = new WeakMap<Page, string[]>()

test.afterEach(async ({ page }) => {
  expect(browserErrors.get(page) ?? []).toEqual([])
})

const sources = Array.from({ length: 12 }, (_, index) => ({
  source_id: `source-${index + 1}`,
  title: index === 1 ? '农业政策来源' : `新闻来源 ${index + 1}`,
  publisher: index % 2 ? '财联社' : '东方财富',
  citation_url: `https://example.com/source-${index + 1}`,
}))

const baseSections = Array.from({ length: 8 }, (_, index) => ({
  section_id: `section-${index + 1}`,
  heading: index === 0 ? '农业板块' : `分析章节 ${index + 1}`,
  body: `这是第 ${index + 1} 个分析章节的正文。`.repeat(16),
  source_ids: index === 0 ? ['source-2'] : [`source-${Math.min(index + 2, 12)}`],
}))

function run(index = 1) {
  return {
    run_id: `review-run-${index}`, requested_at: '2026-08-28T08:00:00Z', provider: 'fixture',
    status: 'READY_FOR_HUMAN_REVIEW', elapsed_ms: 100, total_cost_cny: '0',
    draft_id: `draft-${index}`, sector_count: 8,
  }
}

async function installReviewFixture(page: Page, mode: FixtureMode = 'pending') {
  const state = { patchCount: 0, version: 2, introduction: '当前导语', conflictReturned: false }
  const errors: string[] = []
  browserErrors.set(page, errors)
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (event) => {
    if (event.type() !== 'error') return
    const message = event.text()
    const expectedHttpFailure = (mode === 'failed' && message.includes('503'))
      || (mode === 'conflict' && message.includes('409'))
    if (!expectedHttpFailure) errors.push(message)
  })

  const fulfill = (route: Route, json: unknown, status = 200) => route.fulfill({ json, status })
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/api/runs') {
      if (mode === 'loading') await new Promise((resolve) => setTimeout(resolve, 250))
      if (mode === 'empty') return fulfill(route, [])
      const items = Array.from({ length: 12 }, (_, index) => run(index + 1))
      if (mode === 'approved') items[0].review_decision = 'APPROVED_FOR_COPY'
      return fulfill(route, items)
    }
    if (/\/api\/runs\/[^/]+\/draft$/.test(path)) {
      const latest = {
        version: state.version, status: 'READY_FOR_HUMAN_REVIEW', titles: ['农业、医药与消费板块复盘'],
        introduction: state.introduction, sections: baseSections, conclusion: '综合来看，板块表现分化。',
        risk_notice: '以上内容仅用于信息复盘，不构成投资建议。', sources, character_count: 4200,
      }
      return fulfill(route, { versions: [{ ...latest, version: 1, introduction: '历史导语' }, latest] })
    }
    if (path.endsWith('/governance')) return fulfill(route, mode === 'blocked'
      ? { status: 'FAIL', rules_version: 'v1', issues: [{ code: 'MISSING_SOURCE', message: '农业结论缺少足够来源', severity: 'ERROR' }] }
      : { status: 'PASS', rules_version: 'v1', issues: [] })
    if (path.endsWith('/approval') && request.method() === 'GET') return fulfill(route, mode === 'approved'
      ? { draft_id: 'draft-1', version: state.version, status: 'APPROVED_FOR_COPY', actor: 'reviewer' }
      : null)
    if (path.endsWith('/evidence-decisions') && request.method() === 'GET') return fulfill(route, [])
    if (path.endsWith('/evidence-decisions') && request.method() === 'POST') {
      const body = request.postDataJSON() as { source_id: string; decision: 'KEEP'; reason: string }
      return fulfill(route, { decision_id: 'decision-1', draft_version: state.version, ...body, affected_section_ids: ['section-1'], created_at: '2026-08-28T08:20:00Z' }, 201)
    }
    if (path.endsWith('/patches') && request.method() === 'POST') {
      state.patchCount += 1
      if (mode === 'failed') return fulfill(route, { detail: 'temporary unavailable' }, 503)
      if (mode === 'conflict' && !state.conflictReturned) {
        state.conflictReturned = true
        state.version += 1
        return fulfill(route, { detail: 'draft version conflict' }, 409)
      }
      const body = request.postDataJSON() as { operations: Array<{ path: string; value: string }> }
      const operation = body.operations[0]
      if (operation.path === 'introduction') state.introduction = operation.value
      state.version += 1
      return fulfill(route, { draft_id: 'draft-1', version: state.version, status: 'READY_FOR_HUMAN_REVIEW', content: {} }, 201)
    }
    if (path.endsWith('/approve') && request.method() === 'POST') return fulfill(route, { draft_id: 'draft-1', version: state.version, status: 'APPROVED_FOR_COPY', actor: 'reviewer' })
    if (path.endsWith('/revoke') && request.method() === 'POST') return fulfill(route, { draft_id: 'draft-1', version: state.version, status: 'REVOKED', actor: 'reviewer' })
    if (path.endsWith('/return') && request.method() === 'POST') return fulfill(route, { draft_id: 'draft-1', version: state.version, status: 'RETURNED', actor: 'reviewer' })
    return fulfill(route, { detail: `Unhandled fixture path: ${path}` }, 404)
  })
  return state
}

async function openReview(page: Page, viewport: { width: number; height: number }, mode: FixtureMode = 'pending') {
  const state = await installReviewFixture(page, mode)
  await page.setViewportSize(viewport)
  await page.goto('/review')
  if (mode !== 'empty') await expect(page.getByRole('region', { name: '审核主工作区' })).toBeVisible()
  return state
}

for (const viewport of [{ width: 1536, height: 1024 }, { width: 1440, height: 900 }]) {
  test(`desktop review uses balanced independent panes at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await openReview(page, viewport)
    const panes = page.locator('.review-workspace__pane')
    const boxes = await Promise.all([0, 1, 2].map((index) => panes.nth(index).boundingBox()))
    const total = boxes.reduce((sum, box) => sum + (box?.width ?? 0), 0)
    expect((boxes[0]?.width ?? 0) / total).toBeGreaterThan(0.20)
    expect((boxes[1]?.width ?? 0) / total).toBeGreaterThan(0.50)
    expect((boxes[1]?.width ?? 0) / total).toBeLessThan(0.56)
    expect((boxes[2]?.width ?? 0) / total).toBeGreaterThan(0.23)
    await panes.nth(0).evaluate((element) => { element.scrollTop = 180 })
    expect(await panes.nth(0).evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
    expect(await panes.nth(1).evaluate((element) => element.scrollTop)).toBe(0)
    await panes.nth(1).evaluate((element) => { element.scrollTop = 220 })
    expect(await panes.nth(1).evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })
}

for (const viewport of [{ width: 1024, height: 768 }, { width: 768, height: 1024 }, { width: 390, height: 844 }]) {
  test(`responsive review switches panes without root overflow at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await openReview(page, viewport)
    const tabs = page.getByRole('tablist', { name: '审核工作区视图' })
    await expect(tabs).toBeVisible()
    await page.getByRole('tab', { name: '队列', exact: true }).click()
    await expect(page.getByRole('tabpanel', { name: '队列' })).toBeVisible()
    await page.getByRole('tab', { name: '证据', exact: true }).click()
    await expect(page.getByRole('tabpanel', { name: '证据' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })
}

test('focused section drives evidence and autosave persists after 800ms', async ({ page }) => {
  const state = await openReview(page, { width: 1536, height: 1024 })
  await page.getByLabel('农业板块').focus()
  await expect(page.getByText('与「农业板块」相关的来源')).toBeVisible()
  const sourceList = page.getByRole('list', { name: '审核来源' })
  await expect(sourceList.getByText('农业政策来源')).toBeVisible()
  await expect(sourceList.getByText('新闻来源 1')).toHaveCount(0)

  await page.getByLabel('导语').fill('自动保存后的导语')
  await expect.poll(() => state.patchCount, { timeout: 2500 }).toBe(1)
  await expect(page.getByLabel('导语')).toHaveValue('自动保存后的导语')
  await expect(page.getByText('所有更改已保存')).toBeVisible()
})

test('historical versions remain read-only and cannot be approved', async ({ page }) => {
  await openReview(page, { width: 1440, height: 900 })
  await page.getByLabel('查看草稿版本').selectOption('1')
  await expect(page.getByLabel('导语')).toHaveAttribute('readonly', '')
  await expect(page.getByText('正在查看历史版本，不能批准。')).toBeVisible()
  await expect(page.getByRole('button', { name: '批准复制' })).toBeDisabled()
})

for (const mode of ['failed', 'conflict'] as const) {
  test(`${mode} autosave preserves local text and exposes recovery`, async ({ page }) => {
    await openReview(page, { width: 1440, height: 900 }, mode)
    await page.getByLabel('导语').fill(`${mode} 本地文本`)
    await expect(page.getByRole('button', { name: '重试保存导语' })).toBeVisible({ timeout: 2500 })
    await expect(page.getByLabel('导语')).toHaveValue(`${mode} 本地文本`)
    await expect(page.getByRole('button', { name: '批准复制' })).toBeDisabled()
  })
}

test('loading, empty, governance-blocked and approved states remain explicit', async ({ page }) => {
  await installReviewFixture(page, 'loading')
  await page.goto('/review')
  await expect(page.getByText('正在加载审核队列…')).toBeVisible()
  await expect(page.getByRole('region', { name: '审核主工作区' })).toBeVisible()

  await page.unroute('**/api/**')
  await installReviewFixture(page, 'empty')
  await page.reload()
  await expect(page.getByRole('heading', { name: '暂无可审核草稿' })).toBeVisible()

  await page.unroute('**/api/**')
  await installReviewFixture(page, 'blocked')
  await page.reload()
  await expect(page.getByText('治理检查未通过，不能批准。')).toBeVisible()

  await page.unroute('**/api/**')
  await installReviewFixture(page, 'approved')
  await page.reload()
  await expect(page.getByRole('link', { name: '导出已批准版本' })).toBeVisible()
})
