import { useMemo, useState } from 'react'
import type { OperationsSummary, OperationsTrendPoint } from '../../operationsApi'
import Panel from '../ui/Panel'

const WIDTH = 720
const HEIGHT = 238
const PADDING = { top: 24, right: 18, bottom: 38, left: 42 }

function toUtcDay(value: string) {
  const date = new Date(value)
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate())
}

function filterRange(points: OperationsTrendPoint[], generatedAt: string, days: 7 | 30) {
  const end = toUtcDay(generatedAt)
  const start = end - (days - 1) * 86_400_000
  return points.filter((point) => {
    const day = toUtcDay(point.date)
    return day >= start && day <= end
  })
}

function linePoints(points: OperationsTrendPoint[], key: 'total' | 'completed' | 'failed', maximum: number) {
  const innerWidth = WIDTH - PADDING.left - PADDING.right
  const innerHeight = HEIGHT - PADDING.top - PADDING.bottom
  return points.map((point, index) => {
    const x = PADDING.left + (points.length === 1 ? innerWidth / 2 : (index / (points.length - 1)) * innerWidth)
    const y = PADDING.top + innerHeight - (point[key] / maximum) * innerHeight
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

function formatDay(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', timeZone: 'UTC' }).format(new Date(value))
}

export default function OperationsTrendPanel({ trend, generatedAt }: {
  trend: OperationsSummary['trend']
  generatedAt: string
}) {
  const [range, setRange] = useState<7 | 30>(7)
  const points = useMemo(() => filterRange(trend.points, generatedAt, range), [generatedAt, range, trend.points])
  const total = points.reduce((sum, point) => sum + point.total, 0)
  const maximum = Math.max(1, ...points.flatMap((point) => [point.total, point.completed, point.failed]))
  const noRangeData = trend.available && points.length === 0
  const description = points.length > 0
    ? `最近 ${range} 天共 ${total} 次运行`
    : (noRangeData ? `最近 ${range} 天没有运行记录` : trend.reason ?? '趋势数据暂不可用')

  return (
    <Panel
      className="operations-trend"
      title="运行趋势"
      description="按持久化运行记录聚合总量、完成和失败。"
      actions={(
        <div className="operations-segmented" aria-label="趋势时间范围">
          {([7, 30] as const).map((days) => (
            <button key={days} type="button" aria-pressed={range === days} onClick={() => setRange(days)}>近 {days} 天</button>
          ))}
        </div>
      )}
    >
      {points.length > 0 && <p className="operations-trend__summary" aria-live="polite">{description}</p>}
      {points.length > 0 && (
        <>
          <div className="operations-trend__legend" aria-hidden="true">
            <span data-series="total">总运行</span>
            <span data-series="completed">完成</span>
            <span data-series="failed">失败</span>
          </div>
          <svg className="operations-trend__chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`最近 ${range} 天运行趋势`} preserveAspectRatio="none">
            {[0, 0.5, 1].map((ratio) => {
              const y = PADDING.top + (HEIGHT - PADDING.top - PADDING.bottom) * ratio
              return <line key={ratio} x1={PADDING.left} y1={y} x2={WIDTH - PADDING.right} y2={y} className="operations-trend__gridline" />
            })}
            <polyline className="operations-trend__line operations-trend__line--total" points={linePoints(points, 'total', maximum)} />
            <polyline className="operations-trend__line operations-trend__line--completed" points={linePoints(points, 'completed', maximum)} />
            <polyline className="operations-trend__line operations-trend__line--failed" points={linePoints(points, 'failed', maximum)} />
            {points.map((point, index) => {
              const x = PADDING.left + (points.length === 1 ? (WIDTH - PADDING.left - PADDING.right) / 2 : (index / (points.length - 1)) * (WIDTH - PADDING.left - PADDING.right))
              return <text key={point.date} x={x} y={HEIGHT - 12} textAnchor="middle">{formatDay(point.date)}</text>
            })}
          </svg>
        </>
      )}
      {points.length === 0 && <div className="operations-trend__empty"><p>{description}</p><span>产生真实运行记录后，这里会自动显示趋势。</span></div>}
    </Panel>
  )
}
