import { expect, it } from 'vitest'
import { formatDuration, isActiveRun, providerLabel, runCost, downgradeLabel } from './runPresentation'

it('distinguishes recorded zero, missing cost, active cost and inapplicable data cost', () => {
  expect(runCost('0', 'COMPLETED')).toBe('¥0')
  expect(runCost(null, 'COMPLETED')).toBe('未记录')
  expect(runCost(null, 'RUNNING')).toBe('待完成')
  expect(runCost(null, 'FAILED', true)).toBe('不适用')
  expect(formatDuration(null, 'FAILED')).toBe('未记录')
  expect(formatDuration(0, 'COMPLETED')).toBe('0 ms')
})

it('recognizes collecting stages without inventing active unknown statuses', () => {
  expect(isActiveRun('FETCHING_MARKET')).toBe(true)
  expect(isActiveRun('QUEUED')).toBe(true)
  expect(isActiveRun('RETRY_WAITING')).toBe(true)
  expect(isActiveRun('READY_FOR_ATTRIBUTION')).toBe(false)
  expect(isActiveRun('NEW_UNKNOWN_STATUS')).toBe(false)
  expect(providerLabel('live')).toBe('实时数据')
  expect(providerLabel(undefined)).toBe('未记录')
  expect(providerLabel('custom-source')).toBe('custom-source')
})

it('explains known downgrade codes and preserves unknown messages', () => {
  expect(downgradeLabel('CUTOFF_VIOLATION')).toBe('部分新闻晚于数据截止时间，不能用于本次分析')
  expect(downgradeLabel('CORE_SOURCES_UNAVAILABLE')).toBe('核心新闻来源均不可用，请检查数据源后重试')
  expect(downgradeLabel('NEW_CODE')).toBe('NEW_CODE')
})
