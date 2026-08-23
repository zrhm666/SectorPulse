import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import EmptyState from '../components/ui/EmptyState'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import StatusBadge from '../components/ui/StatusBadge'
import { fetchOperationsSummary, type OperationsSummary } from '../operationsApi'

type MetricCardProps = { label: string; value: number; description: string; tone?: 'default' | 'warning' | 'danger' }

function MetricCard({ label, value, description, tone = 'default' }: MetricCardProps) {
  return <article className={`metric-card metric-card--${tone}`}><p>{label}</p><strong>{value}</strong><span>{description}</span></article>
}

export default function OperationsDashboardPage() {
  const [summary, setSummary] = useState<OperationsSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      setSummary(await fetchOperationsSummary())
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  return (
    <section>
      <PageHeader
        eyebrow="日常管理"
        title="运营总览"
        description="查看真实运行、复核队列与系统就绪状态。"
        actions={<><button className="button button-secondary" type="button" onClick={() => void load()}>刷新状态</button><Link className="button button-primary" to="/runs">新建分析</Link></>}
      />
      {loading && <LoadingState label="正在加载运营概览…" />}
      {!loading && error && <InlineAlert tone="error" title="无法加载运营概览">请检查本地服务和数据库连接后重试。<p><button className="button button-secondary" type="button" onClick={() => void load()}>重新加载</button></p></InlineAlert>}
      {!loading && !error && summary && <>
        <div className="metric-grid" aria-label="运营指标">
          <MetricCard label="运行总数" value={summary.runs.total} description={`${summary.runs.running} 个正在执行`} />
          <MetricCard label="待复核" value={summary.runs.awaiting_review} description="等待人工查看" tone="warning" />
          <MetricCard label="失败运行" value={summary.runs.failed} description="需要处理的异常" tone={summary.runs.failed ? 'danger' : 'default'} />
          <MetricCard label="数据源" value={summary.providers.live_data_available ? 1 : 0} description={summary.providers.live_data_available ? '授权已就绪' : '尚未满足运行条件'} tone={summary.providers.live_data_available ? 'default' : 'warning'} />
        </div>
        <div className="dashboard-grid">
          <Panel title="最近运行" description="只显示已有的真实运行记录。" actions={<Link className="button button-ghost" to="/runs">查看全部</Link>}>
            {summary.runs.recent.length === 0 ? <EmptyState title="还没有分析记录" description="从“新建分析”开始第一次运行。" action={<Link className="button button-primary" to="/runs">去新建分析</Link>} /> : <ul className="compact-list" aria-label="最近运行">
              {summary.runs.recent.map((run) => <li key={run.run_id}><Link to={`/runs/${run.run_id}`}><StatusBadge status={run.status} /> <span>{run.run_id.slice(0, 8)}</span><small>{run.provider}</small></Link></li>)}
            </ul>}
          </Panel>
          <Panel title="今日操作建议" description="基于当前配置和运行状态生成。">
            <ul className="check-list">
              <li>{summary.database.backend === 'postgresql' ? 'PostgreSQL 已连接' : '当前使用 SQLite 本地数据文件'}</li>
              <li>{summary.llm.configured ? `LLM 已配置：${summary.llm.provider}` : 'LLM 配置尚不完整，真实模型不会启动'}</li>
              <li>{summary.providers.live_data_available ? '实时数据授权已就绪' : `实时数据不可用：${summary.providers.missing_requirements.join('、') || '未满足前置条件'}`}</li>
            </ul>
          </Panel>
        </div>
      </>}
    </section>
  )
}
