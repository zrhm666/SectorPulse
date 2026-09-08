import { test, expect } from './fixtures'

test('secondary copy meets contrast and comfortable panels keep content away from edges', async ({ page }) => {
  await page.goto('/runs/new')
  const colors = await page.locator('.page-header__description').evaluate((element) => ({
    foreground: getComputedStyle(element).color,
    background: getComputedStyle(document.documentElement).getPropertyValue('--sp-bg').trim(),
  }))
  function luminance(value: string) {
    const channels = value.startsWith('#') ? value.slice(1).match(/../g)!.map(v => parseInt(v, 16)) : value.match(/\d+/g)!.slice(0, 3).map(Number)
    const linear = channels.map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]
  }
  expect((luminance(colors.background) + .05) / (luminance(colors.foreground) + .05)).toBeGreaterThanOrEqual(4.5)
  expect(await page.locator('.panel').first().evaluate(e => parseFloat(getComputedStyle(e).paddingLeft))).toBeGreaterThanOrEqual(18)
})

test.describe('failure presentation', () => {
  test.use({ allowedHttpErrorStatuses: [503] })
  test('errors have aligned icon and actionable retry', async ({ page }) => {
    await page.route('**/api/runs', route => route.fulfill({ status: 503, json: { detail: 'temporarily unavailable' } }))
    await page.goto('/runs')
    const alert = page.getByRole('alert')
    await expect(alert).toContainText('无法加载运行记录')
    expect(await alert.evaluate(e => getComputedStyle(e).display)).toBe('grid')
    expect(await alert.evaluate(e => getComputedStyle(e).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)')
    await expect(page.getByRole('button', { name: '重新加载' })).toBeVisible()
    await page.screenshot({ path: test.info().outputPath('failure.png') })
  })
})

for (const width of [1440, 1024, 390]) {
  test(`recent registry restores URL and paginates at ${width}`, async ({ page }) => {
    await page.route('**/api/runs', route => route.fulfill({ json: Array.from({ length: 45 }, (_, i) => ({ run_id: `recent-${String(i).padStart(2, '0')}`, provider: 'live', status: 'FAILED', requested_at: new Date(Date.UTC(2026, 8, 8) - i * 1000).toISOString(), elapsed_ms: null, total_cost_cny: null, draft_id: null })) }))
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/runs?status=FAILED&page=3')
    await expect(page.getByTitle('recent-44')).toBeVisible()
    await expect(page.getByTitle('recent-00')).toHaveCount(0)
    await page.getByRole('searchbox', { name: '搜索近期运行' }).fill('RECENT-00')
    await expect(page).not.toHaveURL(/page=3/)
    await expect(page.getByTitle('recent-00')).toBeVisible()
    await page.reload()
    await expect(page.getByRole('searchbox', { name: '搜索近期运行' })).toHaveValue('RECENT-00')
    for (const control of [page.getByRole('searchbox', { name: '搜索近期运行' }), page.getByLabel('按状态筛选')]) {
      expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(width < 769 ? 44 : 40)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: test.info().outputPath(`registry-${width}.png`) })
  })
}
