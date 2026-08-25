import type { AppIconName } from '../components/ui/AppIcon'

export type NavigationItem = {
  label: string
  to: string
  exact?: boolean
  icon: AppIconName
  group: '运营' | '管理'
}

export const NAV_ITEMS: NavigationItem[] = [
  { label: '运营总览', to: '/', exact: true, icon: 'home', group: '运营' },
  { label: '分析运行', to: '/runs', icon: 'runs', group: '运营' },
  { label: '审核工作台', to: '/review', icon: 'review', group: '运营' },
  { label: '定时任务', to: '/schedules', icon: 'calendar', group: '管理' },
  { label: '系统状态', to: '/system', icon: 'system', group: '管理' },
  { label: '影子验收', to: '/shadow-acceptance', icon: 'shield', group: '管理' },
]
