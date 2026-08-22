import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchRuns, type RunSummary } from '../api'
import EmptyState from '../components/ui/EmptyState'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import StatusBadge from '../components/ui/StatusBadge'
import NewRunDialog from '../components/NewRunDialog'
import { createDataRun } from '../dataRunsApi'

export default function RunListPage() {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const navigate = useNavigate()

  const startDataRun = async (mode: 'intraday' | 'post_close') => {
    const result = await createDataRun({ mode, provider: 'live', precandidate_limit: 30, final_candidate_limit: 12 })
    navigate(`/data-runs/${result.run_id}`)
  }

  useEffect(() => {
    let active = true

    fetchRuns()
      .then((result) => {
        if (active) setRuns(result)
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

  return (
    <section>
      <PageHeader
        title="分析运行"
        description="查看真实运行记录，或立即发起一次分析。"
        actions={(
          <>
            <button className="button button-secondary" type="button" onClick={() => startDataRun('intraday')}>盘中分析</button>
            <button className="button button-secondary" type="button" onClick={() => startDataRun('post_close')}>盘后分析</button>
            <button className="button button-primary" type="button" onClick={() => setShowNew(true)}>新建运行</button>
          </>
        )}
      />
      {showNew && <NewRunDialog onClose={() => setShowNew(false)} />}
      <Panel title="运行历史" description="所有数据均来自现有运行接口。">
        {loading && <LoadingState label="正在加载运行记录…" />}
        {!loading && loadError && (
          <InlineAlert tone="error" title="无法加载运行记录">请稍后刷新页面重试。</InlineAlert>
        )}
        {!loading && !loadError && runs.length === 0 && (
          <EmptyState
            title="还没有运行记录"
            description="创建第一次分析后，运行状态、耗时和成本会显示在这里。"
            action={<button className="button button-primary" type="button" onClick={() => setShowNew(true)}>新建运行</button>}
          />
        )}
        {!loading && !loadError && runs.length > 0 && (
          <ul aria-label="运行记录">
            {runs.map((run) => (
              <li key={run.run_id} className="card">
                <Link to={`/runs/${run.run_id}`}>
                  <StatusBadge status={run.status} />
                  {' '}{run.run_id.slice(0, 8)} · {run.provider} · {run.elapsed_ms != null ? `${run.elapsed_ms}ms` : '耗时待定'}
                  {run.total_cost_cny != null ? ` · ¥${run.total_cost_cny}` : ''}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </section>
  )
}
