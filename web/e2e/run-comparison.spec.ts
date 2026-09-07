import { test, expect } from './fixtures'
import { comparisonFixture, comparisonURL, history, runA, runB } from './run-comparison-fixtures'

// Cancelling obsolete reads is intentional in these navigation tests, including production.
test.use({ allowAbortedGetRequests: true })

test('comparison workspace has a truthful empty state and shared navigation', async ({ page }) => {
  await page.goto('/runs/compare')
  await expect(page.getByRole('heading', { name: '运行对比', exact: true })).toBeVisible()
  await expect(page.getByLabel('当前位置')).toContainText('运行对比')
  await expect(page.locator('a[aria-current="page"]').filter({ hasText: '分析运行' })).toBeVisible()
  await expect(page.getByRole('button', { name: '开始对比', exact: true })).toBeDisabled()
  await expect(page.getByText('选择器可翻阅全部已结束运行')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('selects beyond fifty historical runs, constrains the other side and restores dialog focus', async ({ page }) => {
  const fixture = await comparisonFixture(page)
  await page.goto('/runs/compare')
  const trigger = page.getByRole('button', { name: '选择基准运行', exact: true })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: '选择基准运行' })
  await expect(dialog.getByText('共 55 条 · 1–20')).toBeVisible()
  await dialog.getByRole('button', { name: '关闭', exact: true }).focus()
  await page.keyboard.press('Shift+Tab')
  // Native modal dialogs may visit browser chrome; background page controls must remain inert.
  expect(await dialog.evaluate((element) => element.contains(document.activeElement) || document.activeElement === document.body)).toBe(true)
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: '关闭', exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
  await trigger.press('Enter')
  await dialog.getByRole('button', { name: '下一页' }).click()
  await expect(dialog.getByText('共 55 条 · 21–40')).toBeVisible()
  await dialog.getByRole('button', { name: '下一页' }).click()
  await expect(dialog.getByText('共 55 条 · 41–55')).toBeVisible()
  await dialog.getByRole('button', { name: `选择运行 ${history[54].run_id}`, exact: true }).click()
  await expect(trigger).toBeFocused()
  await page.getByRole('button', { name: '选择对照运行', exact: true }).click()
  const other = page.getByRole('dialog', { name: '选择对照运行' })
  await expect(other.getByLabel('数据来源')).toBeDisabled()
  await expect(other.getByLabel('运行场景')).toBeDisabled()
  await other.getByRole('button', { name: '下一页' }).click()
  await other.getByRole('button', { name: '下一页' }).click()
  await expect(other.getByRole('button', { name: `选择运行 ${history[54].run_id}`, exact: true })).toBeDisabled()
  await other.getByRole('button', { name: '上一页' }).click()
  await other.getByRole('button', { name: '上一页' }).click()
  await other.getByRole('button', { name: `选择运行 ${runB.run_id}`, exact: true }).click()
  await page.getByRole('button', { name: '开始对比', exact: true }).click()
  await expect(page).toHaveURL(comparisonURL(history[54].run_id, runB.run_id))
  await expect(page.getByRole('table', { name: '行业候选与行情' })).toBeVisible()
  expect(fixture.calls.every((call) => call.method === 'GET')).toBe(true)
  expect(fixture.calls.some((call) => call.url.searchParams.get('offset') === '40')).toBe(true)
})

test('restores URL, swaps direction and supports keyboard tabs and browser history', async ({ page }) => {
  await comparisonFixture(page)
  await page.goto(comparisonURL())
  await expect(page.getByText('上升 3 位')).toBeVisible()
  const tab = page.getByRole('tab', { name: '候选与行情', exact: true })
  await tab.focus()
  await tab.press('ArrowRight')
  await expect(page.getByRole('tab', { name: '新闻记录', exact: true })).toBeFocused()
  await expect(page.getByText('共 25 条', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('tab', { name: '新闻记录', exact: true })).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('button', { name: '交换基准与对照' }).click()
  await expect(page).toHaveURL(comparisonURL(runB.run_id, runA.run_id, 'news'))
  await expect(page.getByText('两次均留存 10 · 仅基准留存 10 · 仅对照留存 5')).toBeVisible()
  await page.goBack()
  await expect(page).toHaveURL(comparisonURL(runA.run_id, runB.run_id, 'news'))
  await expect(page.getByText('两次均留存 10 · 仅基准留存 5 · 仅对照留存 10')).toBeVisible()
  await page.goForward()
  await expect(page).toHaveURL(comparisonURL(runB.run_id, runA.run_id, 'news'))
  await page.getByRole('tab', { name: '候选与行情', exact: true }).click()
  await expect(page.getByText('下降 3 位')).toBeVisible()
})

test('pages news, resets membership filters and retains safe, accessible details', async ({ page }) => {
  const fixture = await comparisonFixture(page)
  await page.goto(comparisonURL(runA.run_id, runB.run_id, 'news'))
  await expect(page.getByText('共 25 条 · 1–20')).toBeVisible()
  const unsafe = page.locator('.comparison-news-item').filter({ hasText: '验收示例新闻 2' }).first()
  const expand = unsafe.getByRole('button')
  await expand.focus(); await expand.press('Enter')
  await expect(expand).toHaveAttribute('aria-expanded', 'true')
  const controlled = await expand.getAttribute('aria-controls')
  expect(controlled).toBeTruthy()
  await expect(page.locator(`[id="${controlled}"]`)).toHaveText('<script>unsafe()</script>')
  await expect(unsafe.getByRole('link')).toHaveCount(0)
  await expect(unsafe.locator('script')).toHaveCount(0)
  await expect(unsafe.locator('time')).toBeVisible()
  await page.getByRole('button', { name: '下一页' }).click()
  await expect(page.getByText('共 25 条 · 21–25')).toBeVisible()
  await page.getByLabel('新闻成员关系').selectOption('ONLY_COMPARE')
  await expect(page.getByText('共 10 条 · 1–10')).toBeVisible()
  await expect(page.getByRole('button', { name: '下一页' })).toBeDisabled()
  expect(fixture.calls.every((call) => call.method === 'GET')).toBe(true)
})

test.describe('recoverable failures', () => {
  test.use({ allowedHttpErrorStatuses: [503] })
  test('retries overview and individual panels without losing the selected pair', async ({ page }) => {
    const fixture = await comparisonFixture(page)
    fixture.faults.overview = true
    await page.goto(comparisonURL())
    await expect(page.getByText('运行对比失败', { exact: true })).toBeVisible()
    fixture.faults.overview = false
    await page.getByRole('button', { name: '重试对比', exact: true }).click()
    await expect(page.getByText('上升 3 位')).toBeVisible()
    fixture.faults.news = true
    await page.getByRole('tab', { name: '新闻记录', exact: true }).click()
    await expect(page.getByText('新闻记录读取失败')).toBeVisible()
    fixture.faults.news = false
    await page.getByRole('button', { name: '重试', exact: true }).click()
    await expect(page.getByText('共 25 条', { exact: true })).toBeVisible()
    fixture.faults.evidence = true
    await page.getByRole('tab', { name: '板块证据', exact: true }).click()
    await expect(page.getByText('证据关系读取失败')).toBeVisible()
    fixture.faults.evidence = false
    await page.getByRole('button', { name: '重试', exact: true }).click()
    await expect(page.getByText('事件：示例事件')).toBeVisible()
    await expect(page.getByText(/规则版本：v1/).first()).toBeVisible()
    await expect(page).toHaveURL(comparisonURL(runA.run_id, runB.run_id, 'evidence'))
  })
})

test('a delayed response from the old pair cannot replace the swapped result', async ({ page }) => {
  const fixture = await comparisonFixture(page)
  fixture.holdNews()
  await page.goto(comparisonURL(runA.run_id, runB.run_id, 'news'))
  await expect.poll(() => fixture.delayed.length).toBeGreaterThan(0)
  await page.getByRole('button', { name: '交换基准与对照' }).click()
  await expect(page.getByText('两次均留存 10 · 仅基准留存 10 · 仅对照留存 5')).toBeVisible()
  await fixture.releaseNews()
  await expect(page.getByText('共 25 条', { exact: true })).toBeVisible()
  await expect(page.getByText(/999/)).toHaveCount(0)
})

for (const viewport of [{ width: 1440, height: 900 }, { width: 1024, height: 768 }, { width: 390, height: 844 }]) {
  test(`populated comparison remains usable at ${viewport.width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    await comparisonFixture(page)
    await page.goto(comparisonURL())
    const row = page.getByRole('row', { name: /半导体/ })
    await row.getByRole('button', { name: '查看详情' }).click()
    await expect(page.getByText('字段口径未知')).toBeVisible()
    await expect(page.getByText('示例甲')).toBeVisible()
    const sourceDetails = page.getByText('查看行业来源与字段口径', { exact: true })
    await sourceDetails.focus(); await sourceDetails.press('Enter')
    await expect(page.getByText('fixture-market', { exact: true }).first()).toBeVisible()
    await sourceDetails.press('Enter')
    await page.getByRole('combobox', { name: '入选关系', exact: true }).selectOption('ONLY_COMPARE')
    await expect(page.getByRole('row', { name: /半导体/ })).toHaveCount(0)
    await expect(page.getByRole('row', { name: /人工智能/ })).toBeVisible()
    await page.getByRole('combobox', { name: '入选关系', exact: true }).selectOption('ALL')
    const overflow = await page.evaluate(() => ({ root: document.documentElement.scrollWidth > innerWidth,
      tables: Array.from(document.querySelectorAll('.comparison-table-wrap')).some((element) => element.scrollWidth > element.clientWidth) }))
    expect(overflow.root).toBe(false)
    if (viewport.width < 720) expect(overflow.tables).toBe(false)
    await page.getByRole('heading', { name: '运行对比', exact: true }).scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath(`comparison-${viewport.width}.png`) })
    const sidebar = page.locator('.sidebar-nav')
    const before = viewport.width > 1024 ? await sidebar.boundingBox() : null
    if (before) {
      const navigationLayout = await page.locator('.sidebar-nav__link').first().evaluate((element) => {
        const icon = element.querySelector('svg')!.getBoundingClientRect()
        const label = element.querySelector('span')!.getBoundingClientRect()
        return { aligned: Math.abs(icon.y + icon.height / 2 - label.y - label.height / 2) < 2, underlined: getComputedStyle(element).textDecorationLine.includes('underline') }
      })
      expect(navigationLayout).toEqual({ aligned: true, underlined: false })
    }
    await page.getByRole('tabpanel').scrollIntoViewIfNeeded()
    if (before) expect((await sidebar.boundingBox())?.y).toBe(before.y)
    await page.screenshot({ path: testInfo.outputPath(`comparison-results-${viewport.width}.png`) })
  })
}

test('comparison page remains readable on a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/runs/compare')
  await expect(page.getByRole('heading', { name: '运行对比', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
