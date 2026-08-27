import type { OperationsSummary } from '../../operationsApi'
import MetricCard from '../ui/MetricCard'

export default function OperationsMetricGrid({ summary }: { summary: OperationsSummary['summary'] }) {
  return (
    <section className="operations-metrics" aria-label="核心运营指标">
      <MetricCard icon="runs" label="运行总数" value={summary.total} description="内容与数据运行的去重总数" />
      <MetricCard icon="check" label="今日已完成" value={summary.completed_today} description="今天进入可用终态" tone="success" />
      <MetricCard icon="clock" label="运行中" value={summary.active} description={summary.active > 0 ? '活跃任务每 5 秒自动刷新' : '当前没有活跃任务'} tone={summary.active > 0 ? 'warning' : 'default'} />
      <MetricCard icon="warning" label="异常与待处理" value={summary.attention} description="待审核、降级或失败" tone={summary.attention > 0 ? 'danger' : 'default'} />
    </section>
  )
}
