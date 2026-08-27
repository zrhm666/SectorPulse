export type RouteGroup = '运营' | '管理' | 'SectorPulse'

export type RouteContext = {
  group: RouteGroup
  label: string
}

const EXACT_CONTEXTS: Record<string, RouteContext> = {
  '/': { group: '运营', label: '运营总览' },
  '/runs': { group: '运营', label: '分析运行' },
  '/runs/new': { group: '运营', label: '新建分析' },
  '/review': { group: '运营', label: '审核工作台' },
  '/schedules': { group: '管理', label: '定时任务' },
  '/system': { group: '管理', label: '系统状态' },
  '/shadow-acceptance': { group: '管理', label: '影子验收' },
}

export function resolveRouteContext(pathname: string): RouteContext {
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname
  const exact = EXACT_CONTEXTS[normalized]
  if (exact) return exact
  if (/^\/data-runs\/[^/]+$/.test(normalized)) return { group: '运营', label: '数据运行' }
  if (/^\/runs\/[^/]+$/.test(normalized)) return { group: '运营', label: '内容运行' }
  if (/^\/task-runs\/[^/]+$/.test(normalized)) return { group: '管理', label: '任务运行' }
  return { group: 'SectorPulse', label: '页面' }
}
