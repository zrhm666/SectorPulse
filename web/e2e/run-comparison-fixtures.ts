import type { Page, Route } from '@playwright/test'
import type { Membership, NewsComparisonRow, RunOption } from '../src/runComparisonsApi'
import { runA, runB, sectorComparison, newsComparison, evidenceComparison } from '../src/testComparisonFixtures'

export { runA, runB }
export const history: RunOption[] = [runA, runB, ...Array.from({ length: 53 }, (_, index) => ({
  ...runA, run_id: `00000000-0000-0000-0000-${String(index + 3).padStart(12, '0')}`,
}))]
export const comparisonURL = (base = runA.run_id, compare = runB.run_id, tab = 'sectors') =>
  `/runs/compare?${new URLSearchParams({ base, compare, tab })}`

const reverseMembership = (value: Membership): Membership => value === 'BOTH' ? value : value === 'ONLY_BASE' ? 'ONLY_COMPARE' : 'ONLY_BASE'

export async function comparisonFixture(page: Page) {
  const calls: Array<{ method: string; url: URL }> = []
  const faults = { overview: false, news: false, evidence: false }
  const delayed: Route[] = []
  let holdBaseNews = false
  const documents: NewsComparisonRow[] = Array.from({ length: 25 }, (_, index) => ({
    document_id: `fixture-news-${String(index + 1).padStart(2, '0')}`,
    membership: index < 10 ? 'BOTH' : index < 15 ? 'ONLY_BASE' : 'ONLY_COMPARE',
    metadata: index === 0 ? null : {
      ...newsComparison.items[1].metadata!, title: `验收示例新闻 ${index + 1}`,
      citation_url: index === 1 ? 'javascript:alert(1)' : 'https://example.test/news',
      summary: index === 1 ? '<script>unsafe()</script>' : '浏览器测试使用的示例摘要。',
    },
  }))

  await page.route('**/api/run-comparisons**', async (route) => {
    const request = route.request(), url = new URL(request.url())
    calls.push({ method: request.method(), url })
    if (request.method() !== 'GET') return route.fallback()
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const limit = Number(url.searchParams.get('limit') ?? 20)
    const fail = () => route.fulfill({ status: 503, json: { error: { message: '验收模拟：暂时无法读取，请重试。' } } })
    if (url.pathname.endsWith('/runs')) {
      const items = history.filter((run) => (!url.searchParams.get('provider') || run.provider === url.searchParams.get('provider')) && (!url.searchParams.get('mode') || run.mode === url.searchParams.get('mode')))
      return route.fulfill({ json: { items: items.slice(offset, offset + limit), total: items.length, offset, limit } })
    }
    const base = history.find((run) => run.run_id === url.searchParams.get('base_run_id'))
    const compare = history.find((run) => run.run_id === url.searchParams.get('compare_run_id'))
    if (!base || !compare || base.run_id === compare.run_id) return route.fallback()
    const reversed = base.run_id === runB.run_id
    if (url.pathname === '/api/run-comparisons') {
      if (faults.overview) return fail()
      const view = structuredClone(sectorComparison)
      view.kinds = view.kinds.map((group) => ({ ...group, rows: group.rows.map((row) => structuredClone(row)) }))
      view.base = base; view.compare = compare
      view.warnings = [{ code: 'FIXTURE', side: 'BOTH', kind: null, message: '验收示例数据，仅用于展示交互，不是真实行情。' }]
      view.base_news.recorded_count = reversed ? 20 : 15
      view.compare_news.recorded_count = reversed ? 15 : 20
      view.news_counts = { both: 10, only_base: reversed ? 10 : 5, only_compare: reversed ? 5 : 10 }
      if (reversed) {
        view.candidates.only_base = 1; view.candidates.only_compare = 0
        for (const group of view.kinds) for (const row of group.rows) {
          row.membership = reverseMembership(row.membership)
          ;[row.base_rank, row.compare_rank] = [row.compare_rank, row.base_rank]
          ;[row.base_name, row.compare_name] = [row.compare_name, row.base_name]
          ;[row.base_score, row.compare_score] = [row.compare_score, row.base_score]
          ;[row.base_leader, row.compare_leader] = [row.compare_leader, row.base_leader]
          row.rank_delta = row.rank_delta === null ? null : -row.rank_delta
          for (const metric of [row.pct_change, row.turnover_rate, row.advancers, row.decliners]) {
            ;[metric.base, metric.compare] = [metric.compare, metric.base]
            ;[metric.base_reason, metric.compare_reason] = [metric.compare_reason, metric.base_reason]
            metric.delta = metric.delta === null ? null : metric.delta.startsWith('-') ? metric.delta.slice(1) : `-${metric.delta}`
          }
        }
      }
      return route.fulfill({ json: view })
    }
    if (url.pathname.endsWith('/news')) {
      if (faults.news) return fail()
      if (holdBaseNews && !reversed) { delayed.push(route); return }
      const membership = url.searchParams.get('membership') ?? 'ALL'
      const items = documents.map((item) => ({ ...item, membership: reversed ? reverseMembership(item.membership) : item.membership }))
        .filter((item) => membership === 'ALL' || item.membership === membership)
      return route.fulfill({ json: { ...newsComparison, counts: { both: 10, only_base: reversed ? 10 : 5, only_compare: reversed ? 5 : 10 },
        base_news: { lineage: 'RECORDED', recorded_count: reversed ? 20 : 15 }, compare_news: { lineage: 'RECORDED', recorded_count: reversed ? 15 : 20 },
        items: items.slice(offset, offset + limit), total: items.length, offset, limit } })
    }
    if (url.pathname.endsWith('/evidence')) {
      if (faults.evidence) return fail()
      return route.fulfill({ json: evidenceComparison })
    }
    return route.fallback()
  })
  return { calls, faults, delayed, holdNews: () => { holdBaseNews = true }, releaseNews: async () => {
    holdBaseNews = false
    for (const route of delayed) await route.fulfill({ json: { ...newsComparison, total: 999, items: [] } })
  } }
}
