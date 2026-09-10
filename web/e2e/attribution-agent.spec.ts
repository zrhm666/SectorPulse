import { expect, test } from './fixtures'

test.use({ baseURL: process.env.SECTOR_PULSE_UI_URL || 'http://127.0.0.1:4173' })

for (const width of [1440, 390]) {
  test(`Agent controls and saved trace at ${width}px (synthetic UI data)`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname
      const fulfill = (json: unknown) => route.fulfill({ json })
      if (path === '/api/data-runs/ui-demo') return fulfill({
        run_id: 'ui-demo', provider: 'fixture', mode: 'post_close', status: 'READY_FOR_ATTRIBUTION',
        requested_at: '2026-09-10T08:00:00Z', quality: {}, downgrade_reasons: [],
      })
      if (path.endsWith('/selection')) return fulfill({ confirmed: true, version: 1, selected_sector_ids: ['s1', 's2', 's3'], data_version: 'a'.repeat(64) })
      if (path.endsWith('/content-run')) return fulfill(null)
      if (path.endsWith('/candidates')) return fulfill({ items: [1, 2, 3].map(i => ({ sector_id: `s${i}`, sector_kind: 'INDUSTRY', name: `演练板块${i}`, rank: i, score: '1', reasons: [] })), total: 3, data_version: 'a'.repeat(64) })
      if (path.endsWith('/generate')) {
        expect(route.request().postDataJSON()).toEqual({ attribution_mode: 'agent' })
        return fulfill({ run_id: 'content-demo' })
      }
      if (path === '/api/runs/content-demo') return fulfill({
        run_id: 'content-demo', provider: 'fixture', status: 'READY_FOR_HUMAN_REVIEW',
        attribution_mode: 'agent', requested_at: '2026-09-10T08:00:00Z',
        elapsed_ms: 4000, total_cost_cny: '0', draft_id: null, sector_count: 3,
      })
      if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: 'data: {"type":"done","status":"READY_FOR_HUMAN_REVIEW"}\n\n' })
      if (path.endsWith('/agent-trace')) return fulfill({ steps: [
        { sector_id: 's1', sector_kind: 'INDUSTRY', step: 0, event: { type: 'started', sector_name: '文化传媒（演练）' } },
        { sector_id: 's1', sector_kind: 'INDUSTRY', step: 1, event: { type: 'tool_result', action: { action: 'read_news_detail' }, observation: { status: 'partial', data: { availability: 'summary_only', content: '这是一条用于界面验收的合成摘要，不是真实新闻。' } } } },
        { sector_id: 's1', sector_kind: 'INDUSTRY', step: 2, event: { type: 'stopped', reason: 'AGENT_NO_PROGRESS' } },
      ] })
      return fulfill({ items: [], total: 0, snapshots: [], sectors: [], cards: [], quality: {}, workflow_stage_index: 5, terminal: true, candidate_count: 3, counts: { provider_results: 0, normalized_documents: 0, evidence_events: 0 }, market_sources: [], news_sources: [] })
    })
    await page.goto('/data-runs/ui-demo')
    await expect(page.getByRole('radio', { name: /工作流模式/ })).toBeChecked()
    await page.getByRole('radio', { name: /Agent 模式/ }).check()
    await expect(page.getByRole('button', { name: '生成分析稿' })).toBeEnabled()
    await page.screenshot({ path: info.outputPath(`mode-${width}.png`), fullPage: true })
    await page.getByRole('button', { name: '生成分析稿' }).click()
    await expect(page.getByRole('link', { name: '查看生成进度' })).toBeVisible()
    await page.goto('/runs/content-demo')
    await expect(page.getByText('Agent 查证记录')).toBeAttached()
    await page.screenshot({ path: info.outputPath(`trace-top-${width}.png`), fullPage: true })
    await expect(page.getByText('文化传媒（演练） · 行业')).toBeVisible()
    await page.getByText('查看保存的内容').click()
    await expect(page.getByText('这是一条用于界面验收的合成摘要，不是真实新闻。')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: info.outputPath(`trace-${width}.png`), fullPage: true })
  })
}
