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
        expect(route.request().postData()).toBeNull()
        return fulfill({ run_id: 'content-demo' })
      }
      if (path === '/api/runs/content-demo') return fulfill({
        run_id: 'content-demo', provider: 'fixture', status: 'READY_FOR_HUMAN_REVIEW',
        execution_engine: 'multi_agent', requested_at: '2026-09-10T08:00:00Z',
        elapsed_ms: 4000, total_cost_cny: '0', draft_id: null, sector_count: 3,
      })
      if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: 'data: {"type":"done","status":"READY_FOR_HUMAN_REVIEW"}\n\n' })
      if (path.endsWith('/tasks')) return fulfill({
        recording: 'recorded',
        tasks: [
          { task_id: 'root', parent_id: null, role: 'A0', scope: '分析半导体板块', attempt: 1, status: 'completed', worker_id: null, lease_expires_at: null, public_error_code: null, selection_version: null },
          { task_id: 'research', parent_id: 'root', role: 'A2', scope: 'sector:文化传媒（演练）', attempt: 1, status: 'failed', worker_id: 'w-1', lease_expires_at: null, public_error_code: 'AGENT_NO_PROGRESS', selection_version: null },
        ],
        artifacts: [], tool_invocations: [], model_calls: [], budget: {},
      })
      if (path.endsWith('/agent-trace')) return fulfill({ steps: [
        { sector_id: 's1', sector_kind: 'INDUSTRY', step: 0, event: { type: 'started', sector_name: '文化传媒（演练）' } },
        { sector_id: 's1', sector_kind: 'INDUSTRY', step: 1, event: { type: 'tool_result', action: { action: 'read_news_detail' }, observation: { status: 'partial', data: { availability: 'summary_only', content: '这是一条用于界面验收的合成摘要，不是真实新闻。' } } } },
        { sector_id: 's1', sector_kind: 'INDUSTRY', step: 2, event: { type: 'stopped', reason: 'AGENT_NO_PROGRESS' } },
      ] })
      return fulfill({ items: [], total: 0, snapshots: [], sectors: [], cards: [], quality: {}, workflow_stage_index: 5, terminal: true, candidate_count: 3, counts: { provider_results: 0, normalized_documents: 0, evidence_events: 0 }, market_sources: [], news_sources: [] })
    })
    await page.goto('/data-runs/ui-demo')
    await expect(page.getByRole('radio')).toHaveCount(0)
    await expect(page.getByRole('button', { name: '生成分析稿' })).toBeEnabled()
    await page.screenshot({ path: info.outputPath(`mode-${width}.png`), fullPage: true })
    await page.getByRole('button', { name: '生成分析稿' }).click()
    await expect(page.getByRole('link', { name: '查看生成进度' })).toBeVisible()
    await page.goto('/runs/content-demo')
    // A recorded run shows its own task tree; the fixed stage inference is for legacy runs only.
    const tree = page.getByRole('list', { name: '任务树' })
    await expect(tree).toBeVisible()
    await expect(tree.getByText('分析半导体板块')).toBeVisible()
    await expect(tree.getByText('重复查询，没有新进展')).toBeVisible()
    await expect(page.getByRole('region', { name: '运行阶段' })).toHaveCount(0)
    await expect(page.getByText('Agent 查证记录')).toBeAttached()
    await page.screenshot({ path: info.outputPath(`trace-top-${width}.png`), fullPage: true })
    await expect(page.getByText('文化传媒（演练） · 行业')).toBeVisible()
    await page.getByText('查看保存的内容').click()
    await expect(page.getByText('这是一条用于界面验收的合成摘要，不是真实新闻。')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: info.outputPath(`trace-${width}.png`), fullPage: true })
  })
}
