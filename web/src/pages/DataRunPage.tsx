import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { DataRunCandidateView, DataRunView, fetchDataRun, fetchDataRunCandidates, generateDataRunArticle } from '../dataRunsApi'

export default function DataRunPage() {
  const { runId = '' } = useParams()
  const navigate = useNavigate()
  const [run, setRun] = useState<DataRunView | null>(null)
  const [candidates, setCandidates] = useState<DataRunCandidateView[]>([])
  const [error, setError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)

  useEffect(() => {
    Promise.all([fetchDataRun(runId), fetchDataRunCandidates(runId)])
      .then(([data, items]) => { setRun(data); setCandidates(items) })
      .catch((reason: Error) => setError(reason.message))
  }, [runId])

  const generate = async () => {
    setGenerating(true)
    setError(null)
    try {
      const result = await generateDataRunArticle(runId)
      navigate(`/runs/${result.run_id}`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '生成分析稿失败')
    } finally {
      setGenerating(false)
    }
  }

  if (error) return <p role="alert">{error}</p>
  if (!run) return <p>加载真实数据运行…</p>

  return <section>
    <h1>{run.mode === 'post_close' ? '盘后分析' : '盘中分析'}</h1>
    <p data-testid="run-status">{run.status}</p>
    {run.status === 'READY_FOR_ATTRIBUTION' && <button type="button" onClick={generate} disabled={generating}>
      {generating ? '正在生成…' : '生成分析稿'}
    </button>}
    <h2>质量状态</h2>
    <ul>{Object.entries(run.quality).map(([source, status]) => <li key={source}>{source}: {status}</li>)}</ul>
    {run.downgrade_reasons.length > 0 && <><h2>降级原因</h2><ul>{run.downgrade_reasons.map(reason => <li key={reason}>{reason}</li>)}</ul></>}
    <h2>候选板块</h2>
    <ul>{candidates.map(item => <li key={item.sector_id}>{item.rank}. {item.sector_id} ({item.score})</li>)}</ul>
  </section>
}
