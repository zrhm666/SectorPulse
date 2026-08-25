import type { ReactNode } from 'react'
import AppIcon, { type AppIconName } from './AppIcon'

export default function MetricCard({ icon, label, value, description, progress, tone = 'default' }: {
  icon: AppIconName
  label: string
  value: ReactNode
  description: ReactNode
  progress?: number
  tone?: 'default' | 'success' | 'warning' | 'danger'
}) {
  const normalizedProgress = progress == null ? null : Math.min(100, Math.max(0, progress))
  return (
    <article className="metric-card" data-tone={tone} aria-label={label}>
      <span className="metric-card__icon"><AppIcon name={icon} /></span>
      <span className="metric-card__label">{label}</span>
      <strong className="metric-card__value">{value}</strong>
      <span className="metric-card__description">{description}</span>
      {normalizedProgress != null && <progress value={normalizedProgress} max={100} aria-label={`${label}进度`} />}
    </article>
  )
}
