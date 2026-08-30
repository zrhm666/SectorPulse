import { expect, test } from './fixtures'

test('desktop sidebar stays still while the main region scrolls', async ({ page }) => {
  await page.setViewportSize({ width: 1536, height: 1024 })
  await page.goto('/')
  const sidebar = page.locator('.sidebar-nav')
  const main = page.locator('.app-main')
  await expect(sidebar).toBeVisible()
  await expect(page.getByRole('button', { name: '打开导航' })).toBeHidden()
  const before = await sidebar.boundingBox()
  await main.evaluate((element) => {
    const spacer = document.createElement('div')
    spacer.style.height = '1800px'
    element.append(spacer)
    element.scrollTop = 600
  })
  await expect.poll(() => main.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
  const after = await sidebar.boundingBox()
  expect(after?.y).toBe(before?.y)
  expect(await page.locator('body').evaluate((body) => getComputedStyle(body).overflow)).toBe('hidden')
})

test('navigation becomes a keyboard-dismissible drawer at 1024px and below', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 })
  await page.goto('/runs')
  const menu = page.getByRole('button', { name: '打开导航' })
  await expect(menu).toBeVisible()
  await menu.click()
  await expect(page.getByRole('navigation', { name: '主导航' })).toHaveAttribute('data-open', 'true')
  await expect(page.getByRole('button', { name: '关闭导航', exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.locator('#primary-navigation')).toHaveAttribute('data-open', 'false')
  await expect(menu).toBeFocused()
})

test('shell has no page-level horizontal overflow at 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page.getByRole('button', { name: '打开导航' })).toBeVisible()
})

test('closed mobile navigation is removed from the tab order', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.keyboard.press('Tab')
  const sidebar = page.locator('aside.sidebar-nav')
  await expect(sidebar).toHaveAttribute('aria-hidden', 'true')
  expect(await sidebar.evaluate((element) => !element.contains(document.activeElement))).toBe(true)
})

test('legacy primary page actions keep readable text', async ({ page }) => {
  await page.setViewportSize({ width: 1536, height: 1024 })
  await page.goto('/')
  const action = page.getByRole('link', { name: '新建分析', exact: true }).first()
  await expect(action).toBeVisible()
  expect(await action.evaluate((element) => getComputedStyle(element).color)).toBe('rgb(255, 255, 255)')
})
