// web/src/pages/RunListPage.tsx
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchRuns, RunSummary } from '../api'
import Badge from '../components/Badge'
import NewRunDialog from '../components/NewRunDialog'
import { createDataRun } from '../dataRunsApi'
import { useNavigate } from 'react-router-dom'

const STATUS_TONE: Record<string, 'gray' | 'blue' | 'green' | 'red' | 'orange'> = {
  RUNNING: 'blue',
  READY_FOR_HUMAN_REVIEW: 'green',
  FAILED: 'red',
  CANCELLED: 'gray',
  REVISE_REQUIRED: 'orange',
  UNREVIEWED: 'orange',
  BUDGET_EXCEEDED: 'orange',
  ATTRIBUTION_BLOCKED: 'orange',
  DRAFT_GENERATION_FAILED: 'red',
}

export default function RunListPage() {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [showNew, setShowNew] = useState(false)
  const navigate = useNavigate()

  const startDataRun = async (mode: 'intraday' | 'post_close') => {
    const result = await createDataRun({ mode, provider: 'live', precandidate_limit: 30, final_candidate_limit: 12 })
    navigate(`/data-runs/${result.run_id}`)
  }

  useEffect(() => {
    fetchRuns().then(setRuns).catch(console.error)
  }, [])

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>运行历史</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => startDataRun('intraday')}>盘中分析</button>
          <button onClick={() => startDataRun('post_close')}>盘后分析</button>
          <button onClick={() => setShowNew(true)}>新建运行</button>
        </div>
      </div>
      {showNew && <NewRunDialog onClose={() => setShowNew(false)} />}
      {runs.length === 0 && <p>还没有运行记录，点击「新建运行」开始。</p>}
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {runs.map((r) => (
          <li key={r.run_id} className="card">
            <Link to={`/runs/${r.run_id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <Badge text={r.status} tone={STATUS_TONE[r.status] ?? 'gray'} />
                <span style={{ fontFamily: 'ui-monospace, monospace' }}>{r.run_id.slice(0, 8)}</span>
                <span>{r.provider}</span>
                <span>{r.elapsed_ms != null ? `${r.elapsed_ms}ms` : '…'}</span>
                <span>{r.total_cost_cny != null ? `¥${r.total_cost_cny}` : ''}</span>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
