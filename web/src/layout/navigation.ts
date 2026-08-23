export type NavigationItem = {
  label: string
  to: string
  exact?: boolean
}

export const NAV_ITEMS: NavigationItem[] = [
  { label: '运营总览', to: '/', exact: true },
  { label: '分析运行', to: '/runs' },
  { label: '审核工作台', to: '/review' },
  { label: '定时任务', to: '/schedules' },
  { label: '系统状态', to: '/system' },
  { label: '影子验收', to: '/shadow-acceptance' },
]
