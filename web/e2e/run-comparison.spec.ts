import { test, expect } from './fixtures'

test('comparison workspace has a truthful empty state and shared navigation', async ({ page }) => {
  await page.goto('/runs/compare')
  await expect(page.getByRole('heading', { name: '运行对比', exact: true })).toBeVisible()
  await expect(page.locator('a[aria-current="page"]').filter({ hasText: '分析运行' })).toBeVisible()
  await expect(page.getByRole('button', { name: '开始对比', exact: true })).toBeDisabled()
  await expect(page.getByText('选择器可翻阅全部已结束运行')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: '.impeccable/review/run-comparison-empty.png', fullPage: true })
})

test('comparison page remains readable on a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/runs/compare')
  await expect(page.getByRole('heading', { name: '运行对比', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
