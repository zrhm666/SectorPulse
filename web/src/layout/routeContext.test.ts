import { describe, expect, it } from 'vitest'
import { resolveRouteContext } from './routeContext'

describe('resolveRouteContext', () => {
  it.each([
    ['/', { group: '运营', label: '运营总览' }],
    ['/runs', { group: '运营', label: '分析运行' }],
    ['/runs/new', { group: '运营', label: '新建分析' }],
    ['/runs/run-1', { group: '运营', label: '内容运行' }],
    ['/review', { group: '运营', label: '审核工作台' }],
    ['/data-runs/data-1', { group: '运营', label: '数据运行' }],
    ['/schedules', { group: '管理', label: '定时任务' }],
    ['/task-runs/task-1', { group: '管理', label: '任务运行' }],
    ['/system', { group: '管理', label: '系统状态' }],
    ['/shadow-acceptance', { group: '管理', label: '影子验收' }],
  ])('maps %s to its visible context', (pathname, expected) => {
    expect(resolveRouteContext(pathname)).toEqual(expected)
  })

  it('returns a safe product context for an unknown path', () => {
    expect(resolveRouteContext('/missing')).toEqual({ group: 'SectorPulse', label: '页面' })
  })
})
