export const statusLabels: Record<string, string> = {
  RUNNING: '运行中', READY_FOR_ATTRIBUTION: '等待生成分析稿', READY_FOR_HUMAN_REVIEW: '等待人工审核',
  COMPLETED: '已完成', DEGRADED: '降级完成', FAILED: '运行失败', CANCELLED: '已取消', INTERRUPTED: '已中断',
}

export function statusLabel(status: string) { return statusLabels[status] ?? status }

export function formatDuration(value: number | null) {
  if (value == null) return '待完成'
  return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} 秒`
}

export function formatDate(value: string) {
  if (!value) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}
