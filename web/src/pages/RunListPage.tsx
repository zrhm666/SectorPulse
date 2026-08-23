import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchRuns, type RunSummary } from '../api'
import EmptyState from '../components/ui/EmptyState'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import StatusBadge from '../components/ui/StatusBadge'
import { formatDate, formatDuration } from '../runPresentation'
import { fetchDataRuns, type DataRunView } from '../dataRunsApi'

export default function RunListPage() {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [dataRuns, setDataRuns] = useState<DataRunView[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [providerFilter, setProviderFilter] = useState('ALL')

  useEffect(() => {
    let active = true

    Promise.all([fetchRuns(), fetchDataRuns()])
      .then(([writingResult, dataResult]) => {
        if (active) { setRuns(writingResult); setDataRuns(dataResult ?? []) }
      })
      .catch(() => {
        if (active) setLoadError(true)
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [])

  const rows = [
    ...runs.map((run) => ({ id: run.run_id, status: run.status, mode: '内容生成', provider: run.provider, requestedAt: run.requested_at, elapsed: run.elapsed_ms, cost: run.total_cost_cny, href: `/runs/${run.run_id}` })),
    ...dataRuns.map((run) => ({ id: run.run_id, status: run.status, mode: run.mode === 'post_close' ? '盘后复盘' : '盘中分析', provider: 'data', requestedAt: run.requested_at, elapsed: null, cost: null, href: `/data-runs/${run.run_id}` })),
  ].sort((a, b) => b.requestedAt.localeCompare(a.requestedAt))
  const visibleRuns = rows.filter((run) => (statusFilter === 'ALL' || run.status === statusFilter) && (providerFilter === 'ALL' || run.provider === providerFilter))

  return (
    <section>
      <PageHeader
        title="分析运行"
        description="查看真实运行记录，或立即发起一次分析。"
        actions={<Link className="button button-primary" to="/runs/new">新建分析</Link>}
      />
      <Panel title="运行历史" description="所有数据均来自现有运行接口。">
        {!loading && !loadError && rows.length > 0 && <div className="filter-bar">
          <label>状态<select aria-label="按状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="ALL">全部</option><option value="RUNNING">运行中</option><option value="READY_FOR_HUMAN_REVIEW">待审核</option><option value="FAILED">失败</option></select></label>
          <label>Provider<select aria-label="按 Provider 筛选" value={providerFilter} onChange={(event) => setProviderFilter(event.target.value)}><option value="ALL">全部</option><option value="fixture">Fixture</option><option value="live">Live</option><option value="data">数据运行</option></select></label>
        </div>}
        {loading && <LoadingState label="正在加载运行记录…" />}
        {!loading && loadError && (
          <InlineAlert tone="error" title="无法加载运行记录">请稍后刷新页面重试。</InlineAlert>
        )}
        {!loading && !loadError && rows.length === 0 && (
          <EmptyState
            title="还没有运行记录"
            description="创建第一次分析后，运行状态、耗时和成本会显示在这里。"
            action={<Link className="button button-primary" to="/runs/new">新建分析</Link>}
          />
        )}
        {!loading && !loadError && rows.length > 0 && visibleRuns.length === 0 && <EmptyState title="没有匹配的运行" description="调整筛选条件查看其他运行记录。" />}
        {!loading && !loadError && visibleRuns.length > 0 && <div className="run-table-wrap"><table className="run-table"><thead><tr><th>状态</th><th>运行</th><th>模式</th><th>Provider</th><th>创建时间</th><th>耗时</th><th>成本</th><th><span className="visually-hidden">操作</span></th></tr></thead><tbody>{visibleRuns.map((run) => <tr key={`${run.href}-${run.id}`}><td data-label="状态"><StatusBadge status={run.status} /></td><td data-label="运行"><code title={run.id}>{run.id.slice(0, 8)}</code></td><td data-label="模式">{run.mode}</td><td data-label="Provider">{run.provider === 'data' ? '数据运行' : run.provider}</td><td data-label="创建时间">{formatDate(run.requestedAt)}</td><td data-label="耗时">{formatDuration(run.elapsed)}</td><td data-label="成本">{run.cost != null ? `¥${run.cost}` : '待完成'}</td><td data-label="操作"><Link to={run.href}>查看详情</Link></td></tr>)}</tbody></table></div>}
      </Panel>
    </section>
  )
}
