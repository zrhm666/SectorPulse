export type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

export type StatusBadgeProps = {
  status: string
  label?: string
  tone?: StatusTone
}

const STATUS_DETAILS: Record<string, { label: string; tone: StatusTone }> = {
  RUNNING: { label: '运行中', tone: 'info' },
  QUEUED: { label: '排队中', tone: 'info' },
  RETRY_WAITING: { label: '等待重试', tone: 'warning' },
  READY: { label: '就绪', tone: 'success' },
  READY_FOR_HUMAN_REVIEW: { label: '待人工审核', tone: 'success' },
  APPROVED_FOR_COPY: { label: '已批准', tone: 'success' },
  SUCCESS: { label: '成功', tone: 'success' },
  FAILED: { label: '失败', tone: 'danger' },
  DRAFT_GENERATION_FAILED: { label: '草稿生成失败', tone: 'danger' },
  CANCELLED: { label: '已取消', tone: 'neutral' },
  INTERRUPTED: { label: '已中断', tone: 'danger' },
  REVISE_REQUIRED: { label: '需要修改', tone: 'warning' },
  UNREVIEWED: { label: '未审核', tone: 'warning' },
  BUDGET_EXCEEDED: { label: '预算已用尽', tone: 'warning' },
  ATTRIBUTION_BLOCKED: { label: '归因受阻', tone: 'warning' },
  DEGRADED: { label: '已降级', tone: 'warning' },
  BLOCKED: { label: '已阻塞', tone: 'danger' },
  PENDING: { label: '待处理', tone: 'neutral' },
  EMPTY: { label: '无数据', tone: 'neutral' },
  PARTIAL: { label: '部分完成', tone: 'warning' },
  STALE: { label: '已过期', tone: 'warning' },
  UNAVAILABLE: { label: '不可用', tone: 'danger' },
}

export default function StatusBadge({ status, label, tone }: StatusBadgeProps) {
  const detail = STATUS_DETAILS[status]
  const resolvedTone = tone ?? detail?.tone ?? 'neutral'
  const resolvedLabel = label ?? detail?.label ?? status

  return (
    <span className={`status-badge status-badge--${resolvedTone}`} data-status={status}>
      {resolvedLabel}
    </span>
  )
}
