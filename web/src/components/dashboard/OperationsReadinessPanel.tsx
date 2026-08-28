import { Link } from 'react-router-dom'
import type { OperationsSummary, OperationsReadinessItem } from '../../operationsApi'
import AppIcon, { type AppIconName } from '../ui/AppIcon'
import Panel from '../ui/Panel'
import StatusBadge, { type StatusTone } from '../ui/StatusBadge'

const ITEMS: Array<{ key: keyof OperationsSummary['readiness']; icon: AppIconName }> = [
  { key: 'database', icon: 'system' },
  { key: 'live_data', icon: 'activity' },
  { key: 'llm', icon: 'runs' },
  { key: 'scheduler', icon: 'calendar' },
]

function statusPresentation(item: OperationsReadinessItem): { label: string; tone: StatusTone } {
  if (item.status === 'ready') return { label: '正常', tone: 'success' }
  if (item.status === 'warning') return { label: '需关注', tone: 'warning' }
  if (item.status === 'disabled') return { label: '已停用', tone: 'neutral' }
  return { label: '不可用', tone: 'danger' }
}

export default function OperationsReadinessPanel({ readiness }: { readiness: OperationsSummary['readiness'] }) {
  return (
    <Panel
      className="operations-readiness"
      title="系统就绪状态"
      description="关键依赖的最新检查结果。"
      actions={<Link to="/system">查看系统详情</Link>}
    >
      <ul className="operations-readiness__list">
        {ITEMS.map(({ key, icon }) => {
          const item = readiness[key]
          const presentation = statusPresentation(item)
          return (
            <li key={key}>
              <span className="operations-readiness__icon" data-status={item.status}><AppIcon name={icon} size={18} /></span>
              <span className="operations-readiness__copy"><strong>{item.label}</strong><small>{item.detail}</small></span>
              <StatusBadge status={item.status.toUpperCase()} label={presentation.label} tone={presentation.tone} />
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}
