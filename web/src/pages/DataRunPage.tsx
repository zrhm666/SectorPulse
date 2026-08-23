import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { DataRunCandidateView, DataRunView, fetchDataRun, fetchDataRunCandidates, generateDataRunArticle } from '../dataRunsApi'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import StatusBadge from '../components/ui/StatusBadge'
import { formatDate } from '../runPresentation'

export default function DataRunPage() {
  const { runId = '' } = useParams()
  const navigate = useNavigate()
  const [run, setRun] = useState<DataRunView | null>(null)
  const [candidates, setCandidates] = useState<DataRunCandidateView[]>([])
  const [error, setError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    setError(null)
    Promise.all([fetchDataRun(runId), fetchDataRunCandidates(runId)])
      .then(([data, items]) => { setRun(data); setCandidates(items) })
      .catch(() => setError('无法加载数据运行，请确认服务可用后重试。'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [runId])

  const generate = async () => {
    setGenerating(true)
    setError(null)
    try {
      const result = await generateDataRunArticle(runId)
      navigate(`/runs/${result.run_id}`)
    } catch (reason) {
      setError('分析稿未能生成。请确认 LLM 配置和授权后重试。')
    } finally {
      setGenerating(false)
    }
  }

  if (loading) return <LoadingState label="正在加载数据运行…" />
  if (error && !run) return <InlineAlert tone="error" title="无法加载数据运行">{error}<div><button className="button button-secondary" type="button" onClick={load}>重新加载</button></div></InlineAlert>
  if (!run) return null

  const terminal = ['READY_FOR_ATTRIBUTION', 'DEGRADED', 'FAILED', 'CANCELLED'].includes(run.status)
  const stages = ['采集数据', '质量校验', '筛选候选', '归因就绪']

  return <section>
    <PageHeader title={run.mode === 'post_close' ? '盘后数据运行' : '盘中数据运行'} description={`运行 ${run.run_id.slice(0, 8)} · ${formatDate(run.requested_at)}`} actions={<Link className="button button-secondary" to="/runs">返回运行历史</Link>} />
    <div className="detail-summary detail-summary--compact"><div><span>状态</span><StatusBadge status={run.status} /></div><div><span>场景</span><strong>{run.mode === 'post_close' ? '盘后复盘' : '盘中分析'}</strong></div><div><span>候选板块</span><strong>{candidates.length}</strong></div></div>
    {error && <InlineAlert tone="error" title="操作未完成">{error}</InlineAlert>}
    {run.downgrade_reasons.length > 0 && <InlineAlert tone="warning" title="本次运行存在数据降级"><p>部分来源未达到完整质量要求，结果需要结合以下原因谨慎使用。</p><ul>{run.downgrade_reasons.map(reason => <li key={reason}>{reason}</li>)}</ul></InlineAlert>}
    <Panel title="数据处理进度" description="数据就绪后才能进入分析稿生成。"><ol className="timeline timeline--four">{stages.map((stage) => <li key={stage} data-complete={terminal}><span aria-hidden="true" /><strong>{stage}</strong><small>{terminal ? '已处理' : '进行中'}</small></li>)}</ol></Panel>
    <div className="data-run-grid">
      <Panel title="质量状态" description="按数据来源展示当前可用程度。">{Object.keys(run.quality).length === 0 ? <p className="status-detail">暂无质量状态。</p> : <ul className="quality-list">{Object.entries(run.quality).map(([source, status]) => <li key={source}><strong>{source}</strong><StatusBadge status={status} /></li>)}</ul>}</Panel>
      <Panel title="候选板块" description="按综合评分排序的候选结果。">{candidates.length === 0 ? <p className="status-detail">当前没有候选板块。</p> : <ol className="candidate-list">{candidates.map(item => <li key={item.sector_id}><span>{item.rank}</span><div><strong>{item.sector_id}</strong><small>{item.sector_kind} · 评分 {item.score}</small>{item.reasons.length > 0 && <p>{item.reasons.join('；')}</p>}</div></li>)}</ol>}</Panel>
    </div>
    {run.status === 'READY_FOR_ATTRIBUTION' && <div className="detail-actions"><button className="button button-primary" type="button" onClick={generate} disabled={generating}>{generating ? '正在生成分析稿…' : '生成分析稿'}</button></div>}
  </section>
}
