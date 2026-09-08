export const statusLabels: Record<string, string> = {
  RUNNING: '运行中', READY_FOR_ATTRIBUTION: '等待生成分析稿', READY_FOR_HUMAN_REVIEW: '等待人工审核',
  COMPLETED: '已完成', DEGRADED: '降级完成', FAILED: '运行失败', CANCELLED: '已取消', INTERRUPTED: '已中断',
  PREFLIGHT: '检查运行条件', FETCHING_MARKET: '采集行情', RANKING_PRE_CANDIDATES: '筛选预候选',
  FETCHING_NEWS: '采集新闻', BUILDING_EVIDENCE: '整理证据', BLOCKED: '条件未满足',
}

export function statusLabel(status: string) { return statusLabels[status] ?? status }

export function isActiveRun(status: string) {
  return ['RUNNING', 'QUEUED', 'RETRY_WAITING', 'PREFLIGHT', 'FETCHING_MARKET', 'RANKING_PRE_CANDIDATES', 'FETCHING_NEWS', 'BUILDING_EVIDENCE'].includes(status)
}

export function downgradeLabel(code: string) {
  const labels: Record<string, string> = {
    CUTOFF_VIOLATION: '部分新闻晚于数据截止时间，不能用于本次分析',
    CORE_SOURCES_UNAVAILABLE: '核心新闻来源均不可用，请检查数据源后重试',
  }
  return labels[code] ?? code
}

export function providerLabel(value?: string) {
  return value === 'live' ? '实时数据' : value === 'fixture' ? '样例演练' : value || '未记录'
}

export function runCost(value: string | null, status: string, dataRun = false) {
  if (dataRun) return '不适用'
  return value == null ? (isActiveRun(status) ? '待完成' : '未记录') : `¥${value}`
}

export function formatDuration(value: number | null, status?: string) {
  if (value == null) return status === undefined || isActiveRun(status) ? '待完成' : '未记录'
  return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} 秒`
}

export function formatDate(value: string) {
  if (!value) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}
