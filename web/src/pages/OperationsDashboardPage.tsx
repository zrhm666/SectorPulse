import { Link } from 'react-router-dom'
import OperationsMetricGrid from '../components/dashboard/OperationsMetricGrid'
import OperationsReadinessPanel from '../components/dashboard/OperationsReadinessPanel'
import OperationsTrendPanel from '../components/dashboard/OperationsTrendPanel'
import RecentRunsTable from '../components/dashboard/RecentRunsTable'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import useOperationsSummary from '../hooks/useOperationsSummary'

function formatUpdateTime(value: Date | null) {
  if (!value) return '等待首次更新'
  return `最后更新 ${value.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`
}

export default function OperationsDashboardPage() {
  const { data, initialLoading, refreshing, stale, error, lastSuccessfulAt, refresh } = useOperationsSummary()

  return (
    <section className="dashboard-page operations-dashboard density-comfortable">
      <PageHeader
        eyebrow="Operations"
        title="运营总览"
        description="统一查看真实运行趋势、最近任务与关键依赖状态。"
        meta={<span className="page-header__updated" aria-live="polite">{formatUpdateTime(lastSuccessfulAt)}</span>}
        actions={(
          <>
            <button className="button button--secondary" type="button" disabled={refreshing} onClick={() => void refresh()}>
              {refreshing ? '正在刷新' : '刷新状态'}
            </button>
            <Link className="button button--primary" to="/runs/new">新建分析</Link>
          </>
        )}
      />

      {initialLoading && !data && <LoadingState label="正在加载运营概览…" />}

      {!initialLoading && !data && error && (
        <InlineAlert tone="error" title="无法加载运营概览">
          <p>{error}。请检查本地服务和数据库连接。</p>
          <button className="button button--secondary button--compact" type="button" onClick={() => void refresh()}>重新加载</button>
        </InlineAlert>
      )}

      {data && (
        <>
          {stale && error && (
            <InlineAlert tone="warning" title="当前显示上次成功数据">
              {error}。页面已保留可用内容，你可以手动重试。
            </InlineAlert>
          )}
          <OperationsMetricGrid summary={data.summary} />
          <div className="operations-dashboard__middle">
            <OperationsTrendPanel trend={data.trend} generatedAt={data.generated_at} />
            <OperationsReadinessPanel readiness={data.readiness} />
          </div>
          <RecentRunsTable runs={data.recent_runs} />
        </>
      )}
    </section>
  )
}
