export type NavigationItem = {
  label: string
  to: string
  exact?: boolean
}

export const NAV_ITEMS: NavigationItem[] = [
  { label: '分析运行', to: '/runs' },
  { label: '定时任务', to: '/schedules' },
  { label: '影子验收', to: '/shadow-acceptance' },
]
