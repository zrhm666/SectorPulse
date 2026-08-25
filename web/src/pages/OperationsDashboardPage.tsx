import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import EmptyState from '../components/ui/EmptyState'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import StatusBadge from '../components/ui/StatusBadge'
import MetricCard from '../components/ui/MetricCard'
import { fetchOperationsSummary, type OperationsSummary } from '../operationsApi'

export default function OperationsDashboardPage() {
  const [summary, setSummary] = useState<OperationsSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      setSummary(await fetchOperationsSummary())
      setLastUpdated(new Date())
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const timer = window.setInterval(() => { void load() }, 60_000)
    return () => window.clearInterval(timer)
  }, [load])

  return (
    <section className="dashboard-page density-comfortable">
      <PageHeader
        title="运营总览"
        description="查看真实运行、复核队列与系统就绪状态。"
        actions={<><span className="page-header__updated">{lastUpdated ? `最后更新 ${lastUpdated.toLocaleTimeString('zh-CN')}` : '等待首次更新'}</span><button className="button button-secondary" type="button" onClick={() => void load()}>刷新状态</button><Link className="button button-primary" to="/runs/new">新建分析</Link></>}
      />
      {loading && <LoadingState label="正在加载运营概览…" />}
      {!loading && error && <InlineAlert tone="error" title="无法加载运营概览">请检查本地服务和数据库连接后重试。<p><button className="button button-secondary" type="button" onClick={() => void load()}>重新加载</button></p></InlineAlert>}
      {!loading && !error && summary && <>
        <section className="metric-grid" aria-label="运营指标">
          <MetricCard icon="runs" label="运行总数" value={summary.runs.total} description={`${summary.runs.running} 个正在执行`} />
          <MetricCard icon="review" label="待复核" value={summary.runs.awaiting_review} description="等待人工查看" tone="warning" />
          <MetricCard icon="warning" label="失败运行" value={summary.runs.failed} description="需要处理的异常" tone={summary.runs.failed ? 'danger' : 'default'} />
          <MetricCard icon="shield" label="实时数据" value={summary.providers.live_data_available ? '就绪' : '待配置'} description={summary.providers.live_data_available ? '授权与 Provider 可用' : '尚未满足运行条件'} tone={summary.providers.live_data_available ? 'success' : 'warning'} />
        </section>
        <div className="dashboard-grid">
          <Panel title="最近运行" description="只显示已有的真实运行记录。" actions={<Link className="button button-ghost" to="/runs">查看全部</Link>}>
            {summary.runs.recent.length === 0 ? <EmptyState title="还没有分析记录" description="从“新建分析”开始第一次运行。" action={<Link className="button button-primary" to="/runs">去新建分析</Link>} /> : <ul className="compact-list" aria-label="最近运行">
              {summary.runs.recent.map((run) => <li key={run.run_id}><Link to={`/runs/${run.run_id}`}><StatusBadge status={run.status} /> <span>{run.run_id.slice(0, 8)}</span><small>{run.provider}</small></Link></li>)}
            </ul>}
          </Panel>
          <Panel title="运行条件" description="基于当前配置和运行状态生成。">
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
