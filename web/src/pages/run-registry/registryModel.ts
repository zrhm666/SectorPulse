import type { RunSummary } from '../../api'
import type { DataRunView } from '../../dataRunsApi'
import { isActiveRun } from '../../runPresentation'

export interface RegistryRow {
  id: string
  status: string
  scene: string
  mode: string
  provider: string
  requestedAt: string
  elapsed: number | null
  cost: string | null
  href: string
  error?: string | null
  retryable?: boolean
}

export function registryRows(runs: RunSummary[], dataRuns: DataRunView[]): RegistryRow[] {
  return [
    ...runs.map(run => ({ id: run.run_id, status: run.status, scene: 'content', mode: '内容生成', provider: run.provider, requestedAt: run.requested_at, elapsed: run.elapsed_ms, cost: run.total_cost_cny, href: `/runs/${encodeURIComponent(run.run_id)}`, error: run.error_message, retryable: run.retryable })),
    ...dataRuns.map(run => ({ id: run.run_id, status: run.status, scene: run.mode, mode: run.mode === 'post_close' ? '盘后复盘' : '盘中分析', provider: run.provider ?? '', requestedAt: run.requested_at, elapsed: null, cost: null, href: `/data-runs/${encodeURIComponent(run.run_id)}`, error: run.error_code, retryable: false })),
  ]
}

export function selectRegistry(rows: RegistryRow[], params: URLSearchParams, now: number) {
  const q = (params.get('q') ?? '').trim().toLocaleLowerCase()
  const status = params.get('status') ?? 'ALL'
  const scene = params.get('scene') ?? 'ALL'
  const provider = params.get('provider') ?? 'ALL'
  const days = ({ '24H': 1, '7D': 7, '30D': 30 } as Record<string, number>)[params.get('time') ?? '']
  const filtered = rows.filter(row =>
    (!q || `${row.id} ${row.mode}`.toLocaleLowerCase().includes(q))
    && (status === 'ALL' || (status === 'RUNNING' ? isActiveRun(row.status) : row.status === status))
    && (scene === 'ALL' || row.scene === scene)
    && (provider === 'ALL' || row.provider === provider)
    && (!days || Date.parse(row.requestedAt) >= now - days * 86_400_000),
  ).sort((a, b) => {
    const diff = (Date.parse(a.requestedAt) || 0) - (Date.parse(b.requestedAt) || 0)
    return (params.get('order') === 'asc' ? diff : -diff) || a.href.localeCompare(b.href)
  })
  const pages = Math.max(1, Math.ceil(filtered.length / 20))
  const rawPage = Number(params.get('page') ?? 1)
  const page = Math.min(pages, Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1)
  return { items: filtered.slice((page - 1) * 20, page * 20), total: filtered.length, page, pages }
}

export function registryReturnTo(state: unknown): string {
  const value = state && typeof state === 'object' && 'registryReturnTo' in state ? state.registryReturnTo : null
  return typeof value === 'string' && /^\/runs(?:\?[^\r\n\\]*)?$/.test(value) ? value : '/runs'
}
