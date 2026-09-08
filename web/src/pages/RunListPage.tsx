import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { fetchRuns, type RunSummary } from '../api'
import EmptyState from '../components/ui/EmptyState'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import StatusBadge from '../components/ui/StatusBadge'
import { formatDate, formatDuration, providerLabel, runCost } from '../runPresentation'
import { fetchDataRuns, type DataRunView } from '../dataRunsApi'
import { registryRows, selectRegistry } from './run-registry/registryModel'

export default function RunListPage() {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [dataRuns, setDataRuns] = useState<DataRunView[]>([])
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [params, setParams] = useSearchParams()
  const [loaded, setLoaded] = useState(false)
  const statusFilter = params.get('status') ?? 'ALL'
  const sceneFilter = params.get('scene') ?? 'ALL'
  const providerFilter = params.get('provider') ?? 'ALL'
  const timeFilter = params.get('time') ?? 'ALL'
  const changeFilter = (key: string, value: string) => {
    setParams(previous => {
      const next = new URLSearchParams(previous)
      if (value === 'ALL' || value === '') next.delete(key)
      else next.set(key, value)
      if (key !== 'page') next.delete('page')
      return next
    }, { replace: true })
  }

  useEffect(() => {
    let active = true
    setLoadError(false)
    setLoading(true)

    Promise.all([fetchRuns(), fetchDataRuns()])
      .then(([writingResult, dataResult]) => {
        if (active) { setRuns(writingResult); setDataRuns(dataResult ?? []); setLoaded(true) }
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
  }, [revision])

  const rows = registryRows(runs, dataRuns)
  const result = selectRegistry(rows, params, Date.now())
  const visibleRuns = result.items
  const resetFilters = () => setParams({}, { replace: true })
  const returnTo = '/runs' + (params.size ? `?${params.toString()}` : '')
  const providers = [...new Set(['fixture', 'live', ...rows.map(row => row.provider)])].filter(Boolean)


  return (
    <section className="run-registry-page density-compact">
      <PageHeader
        title="分析运行"
        description="查看真实运行记录，或立即发起一次分析。"
        actions={<><Link className="button button-secondary" to="/runs/compare">运行对比</Link><Link className="button button-primary" to="/runs/new">新建分析</Link></>}
      />
      <Panel title="运行历史" description="近期运行：每类最多 50 条。搜索和筛选仅覆盖已加载记录。" density="compact">
        {loaded && <section className="registry-toolbar" aria-label="运行筛选">
          <div className="registry-toolbar__search">
            <label>搜索近期运行<input type="search" aria-label="搜索近期运行" placeholder="输入运行 ID 或场景" value={params.get('q') ?? ''} onChange={event => changeFilter('q', event.target.value)} /></label>
            <button className="button button-secondary" disabled={loading} type="button" onClick={() => setRevision(value => value + 1)}>{loading ? '正在刷新…' : '刷新记录'}</button>
          </div>
          <div className="registry-quick-filters" role="group" aria-label="常用状态">
            {[['ALL', '全部状态'], ['RUNNING', '运行中'], ['FAILED', '失败'], ['READY_FOR_HUMAN_REVIEW', '待审核']].map(([value, label]) => <button key={value} type="button" className="button button-secondary" aria-pressed={statusFilter === value} onClick={() => changeFilter('status', value)}>{label}</button>)}
          </div>
          <div className="registry-toolbar__fields">
            <label>状态<select aria-label="按状态筛选" value={statusFilter} onChange={(event) => changeFilter('status', event.target.value)}><option value="ALL">全部</option><option value="RUNNING">运行中</option><option value="READY_FOR_HUMAN_REVIEW">待审核</option><option value="FAILED">失败</option></select></label>
            <label>场景<select aria-label="按场景筛选" value={sceneFilter} onChange={(event) => changeFilter('scene', event.target.value)}><option value="ALL">全部</option><option value="content">内容生成</option><option value="intraday">盘中分析</option><option value="post_close">盘后复盘</option></select></label>
            <label>数据来源<select aria-label="按 Provider 筛选" value={providerFilter} onChange={(event) => changeFilter('provider', event.target.value)}><option value="ALL">全部</option>{providers.map(provider => <option key={provider} value={provider}>{providerLabel(provider)}</option>)}</select></label>
            <label>时间<select aria-label="按时间范围筛选" value={timeFilter} onChange={(event) => changeFilter('time', event.target.value)}><option value="ALL">全部时间</option><option value="24H">最近 24 小时</option><option value="7D">最近 7 天</option><option value="30D">最近 30 天</option></select></label>
          </div>
          <div className="registry-toolbar__meta"><span aria-live="polite">显示 {visibleRuns.length} 条，共 {rows.length} 条已加载记录 · 匹配 {result.total} 条</span><label>排序<select aria-label="按创建时间排序" value={params.get('order') === 'asc' ? 'asc' : 'desc'} onChange={event => changeFilter('order', event.target.value)}><option value="desc">最新优先</option><option value="asc">最早优先</option></select></label><button className="button button-secondary" type="button" onClick={resetFilters}>重置筛选</button></div>
        </section>}
        {loading && !loaded && <LoadingState label="正在加载运行记录…" />}
        {!loading && loadError && (
          <InlineAlert tone="error" title="无法加载运行记录">{loaded ? '刷新失败，已保留上次加载的记录和筛选条件。' : '请检查本地服务连接后重试。'}<div><button className="button button-secondary" type="button" onClick={() => setRevision(value => value + 1)}>重新加载</button></div></InlineAlert>
        )}
        {loaded && !loading && !loadError && rows.length === 0 && (
          <EmptyState
            title="还没有运行记录"
            description="创建第一次分析后，运行状态、耗时和成本会显示在这里。"
            action={<Link className="button button-primary" to="/runs/new">新建分析</Link>}
          />
        )}
        {loaded && rows.length > 0 && visibleRuns.length === 0 && <EmptyState title="没有匹配的运行" description="调整筛选条件查看其他运行记录。" />}
        {loaded && visibleRuns.length > 0 && <div className="run-table-wrap"><table className="run-table registry-table"><thead><tr><th>状态</th><th>运行</th><th>模式</th><th>数据来源</th><th>创建时间</th><th>耗时</th><th>成本</th><th><span className="visually-hidden">操作</span></th></tr></thead><tbody>{visibleRuns.map((run) => <tr key={`${run.href}-${run.id}`}><td data-label="状态"><StatusBadge status={run.status} /></td><td data-label="运行"><div className="registry-run-identity"><strong>{formatDate(run.requestedAt).split(' ')[0]}</strong><code title={run.id}>{run.id.slice(0, 8)}</code></div></td><td data-label="模式">{run.mode}</td><td data-label="数据来源">{providerLabel(run.provider)}</td><td data-label="创建时间">{formatDate(run.requestedAt)}</td><td data-label="耗时">{formatDuration(run.elapsed, run.status)}</td><td data-label="成本">{runCost(run.cost, run.status, run.scene !== 'content')}</td><td data-label="操作"><div className="registry-table__actions"><Link to={run.href} state={{ registryReturnTo: returnTo }}>查看详情</Link>{(run.error || run.retryable) && <details className="run-error-detail"><summary role="button">查看错误详情</summary><div className="run-error-detail__body">{run.error && <p>{run.error}</p>}{run.retryable && <p>该运行支持从详情页重新运行。</p>}</div></details>}</div></td></tr>)}</tbody></table></div>}
        {loaded && result.total > 0 && <nav className="registry-pagination" aria-label="运行分页"><button type="button" className="button button-secondary" disabled={result.page <= 1} onClick={() => changeFilter('page', String(result.page - 1))}>上一页</button><span aria-live="polite">第 {result.page} / {result.pages} 页 · 每页 20 条</span><button type="button" className="button button-secondary" disabled={result.page >= result.pages} onClick={() => changeFilter('page', String(result.page + 1))}>下一页</button></nav>}
      </Panel>
    </section>
  )
}
