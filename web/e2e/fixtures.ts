import { expect, test as base } from '@playwright/test'

type E2EOptions = {
  allowedHttpErrorStatuses: number[]
}

export const test = base.extend<E2EOptions>({
  allowedHttpErrorStatuses: [[], { option: true }],
  page: async ({ page, allowedHttpErrorStatuses }, use) => {
    const failures: string[] = []

    await page.route('**/api/**', async (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname

      if (path === '/api/operations/summary' && request.method() === 'GET') {
        await route.fulfill({
          json: {
            database: { backend: 'fixture', name: 'sector_pulse' },
            llm: { provider: 'fixture', model: 'fixture-model', budget_cny_per_run: '0', configured: true },
            consent: { live_data: false, live_llm: false },
            providers: { live_data_available: false, missing_requirements: [] },
            runs: { total: 0, running: 0, awaiting_review: 0, failed: 0, recent: [] },
            summary: { total: 0, completed_today: 0, active: 0, attention: 0 },
            trend: { available: false, reason: '暂无运行记录', points: [] },
            readiness: {
              database: { status: 'ready', label: '数据库', detail: 'Fixture 已就绪', detail_path: '/system' },
              live_data: { status: 'disabled', label: '实时数据', detail: 'E2E Fixture', detail_path: '/system' },
              llm: { status: 'disabled', label: 'LLM', detail: 'E2E Fixture', detail_path: '/system' },
              scheduler: { status: 'disabled', label: '调度器', detail: 'E2E Fixture', detail_path: '/system' },
            },
            recent_runs: [],
            generated_at: '2026-08-30T00:00:00Z',
          },
        })
        return
      }

      if (path === '/api/runs' && request.method() === 'GET') {
        await route.fulfill({ json: [] })
        return
      }

      if (path === '/api/data-runs' && request.method() === 'GET') {
        await route.fulfill({ json: [] })
        return
      }

      failures.push(`unhandled-api: ${request.method()} ${path}`)
      await route.fulfill({
        status: 501,
        json: { error: { code: 'UNHANDLED_E2E_API', message: `${request.method()} ${path}`, retryable: false } },
      })
    })

    page.on('pageerror', (error) => failures.push(`pageerror: ${error.message}`))
    page.on('console', (message) => {
      if (message.type() !== 'error') return
      const text = message.text()
      const isAllowedHttpStatus = allowedHttpErrorStatuses.some((status) => text.includes(`status of ${status}`))
      if (!isAllowedHttpStatus) failures.push(`console: ${text}`)
    })
    page.on('requestfailed', (request) => {
      if (new URL(request.url()).pathname.startsWith('/api/')) {
        failures.push(`requestfailed: ${request.method()} ${request.url()}`)
      }
    })

    await use(page)

    expect(failures, 'browser errors and backend request leaks').toEqual([])
  },
})

export { expect } from '@playwright/test'
