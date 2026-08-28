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
  const [sceneFilter, setSceneFilter] = useState('ALL')
  const [providerFilter, setProviderFilter] = useState('ALL')
  const [timeFilter, setTimeFilter] = useState('ALL')

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
    ...runs.map((run) => ({ id: run.run_id, status: run.status, scene: 'content', mode: '内容生成', provider: run.provider, requestedAt: run.requested_at, elapsed: run.elapsed_ms, cost: run.total_cost_cny, href: `/runs/${run.run_id}`, error: run.error_message, retryable: run.retryable })),
    ...dataRuns.map((run) => ({ id: run.run_id, status: run.status, scene: run.mode, mode: run.mode === 'post_close' ? '盘后复盘' : '盘中分析', provider: 'data', requestedAt: run.requested_at, elapsed: null, cost: null, href: `/data-runs/${run.run_id}`, error: run.error_code, retryable: false })),
  ].sort((a, b) => b.requestedAt.localeCompare(a.requestedAt))
  const timeCutoff = timeFilter === 'ALL' ? null : Date.now() - ({ '24H': 1, '7D': 7, '30D': 30 }[timeFilter] ?? 0) * 86_400_000
  const visibleRuns = rows.filter((run) =>
    (statusFilter === 'ALL' || run.status === statusFilter)
    && (sceneFilter === 'ALL' || run.scene === sceneFilter)
    && (providerFilter === 'ALL' || run.provider === providerFilter)
    && (timeCutoff === null || new Date(run.requestedAt).getTime() >= timeCutoff),
  )

  const resetFilters = () => {
    setStatusFilter('ALL')
    setSceneFilter('ALL')
    setProviderFilter('ALL')
    setTimeFilter('ALL')
  }

  return (
    <section className="run-registry-page density-compact">
      <PageHeader
        title="分析运行"
        description="查看真实运行记录，或立即发起一次分析。"
        actions={<Link className="button button-primary" to="/runs/new">新建分析</Link>}
      />
      <Panel title="运行历史" description="所有数据均来自现有运行接口。" density="compact">
        {!loading && !loadError && rows.length > 0 && <section className="registry-toolbar" aria-label="运行筛选">
          <div className="registry-toolbar__fields">
            <label>状态<select aria-label="按状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="ALL">全部</option><option value="RUNNING">运行中</option><option value="READY_FOR_HUMAN_REVIEW">待审核</option><option value="FAILED">失败</option></select></label>
            <label>场景<select aria-label="按场景筛选" value={sceneFilter} onChange={(event) => setSceneFilter(event.target.value)}><option value="ALL">全部</option><option value="content">内容生成</option><option value="intraday">盘中分析</option><option value="post_close">盘后复盘</option></select></label>
            <label>Provider<select aria-label="按 Provider 筛选" value={providerFilter} onChange={(event) => setProviderFilter(event.target.value)}><option value="ALL">全部</option><option value="fixture">Fixture</option><option value="live">Live</option><option value="data">数据运行</option></select></label>
            <label>时间<select aria-label="按时间范围筛选" value={timeFilter} onChange={(event) => setTimeFilter(event.target.value)}><option value="ALL">全部时间</option><option value="24H">最近 24 小时</option><option value="7D">最近 7 天</option><option value="30D">最近 30 天</option></select></label>
          </div>
          <div className="registry-toolbar__meta"><span aria-live="polite">显示 {visibleRuns.length} 条，共 {rows.length} 条</span><button className="button button-secondary" type="button" onClick={resetFilters}>重置筛选</button></div>
        </section>}
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
        {!loading && !loadError && visibleRuns.length > 0 && <div className="run-table-wrap"><table className="run-table registry-table"><thead><tr><th>状态</th><th>运行</th><th>模式</th><th>Provider</th><th>创建时间</th><th>耗时</th><th>成本</th><th><span className="visually-hidden">操作</span></th></tr></thead><tbody>{visibleRuns.map((run) => <tr key={`${run.href}-${run.id}`}><td data-label="状态"><StatusBadge status={run.status} /></td><td data-label="运行"><code title={run.id}>{run.id.slice(0, 8)}</code></td><td data-label="模式">{run.mode}</td><td data-label="Provider">{run.provider === 'data' ? '数据运行' : run.provider}</td><td data-label="创建时间">{formatDate(run.requestedAt)}</td><td data-label="耗时">{formatDuration(run.elapsed)}</td><td data-label="成本">{run.cost != null ? `¥${run.cost}` : '待完成'}</td><td data-label="操作"><div className="registry-table__actions"><Link to={run.href}>查看详情</Link>{(run.error || run.retryable) && <details className="run-error-detail"><summary role="button">查看错误详情</summary><div className="run-error-detail__body">{run.error && <p>{run.error}</p>}{run.retryable && <p>该运行支持从详情页重新运行。</p>}</div></details>}</div></td></tr>)}</tbody></table></div>}
      </Panel>
    </section>
  )
}
