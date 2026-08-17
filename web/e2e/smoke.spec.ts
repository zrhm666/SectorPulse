import { expect, test } from '@playwright/test'

test('built SPA opens the SectorPulse workbench', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('body')).toContainText('运行')
})
