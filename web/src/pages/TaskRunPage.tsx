import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchTaskRun, TaskRunView } from '../schedulesApi'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import StatusBadge from '../components/ui/StatusBadge'
import SummaryStrip from '../components/ui/SummaryStrip'

export default function TaskRunPage() {
  const { runId } = useParams()
  const [run, setRun] = useState<TaskRunView | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)

  const load = useCallback(async () => {
    if (!runId) return
    setLoading(true); setLoadError(false)
    try { setRun(await fetchTaskRun(runId)) } catch { setLoadError(true) } finally { setLoading(false) }
  }, [runId])
  useEffect(() => { void load() }, [load])

  if (loading && !run) return <LoadingState label="正在加载任务…" />
  if (loadError && !run) return <InlineAlert tone="error" title="无法加载任务"><button className="button button-secondary" type="button" onClick={() => void load()}>重新加载</button></InlineAlert>
  if (!run) return null

  return (
    <section className="management-page task-run-page">
      <PageHeader title={`任务 ${run.run_id.slice(0, 8)}`} description="查看调度任务状态、阶段尝试与降级信息。" />
      <SummaryStrip label="任务摘要" items={[{ label: '状态', value: <StatusBadge status={run.status} /> }, { label: 'Provider', value: run.provider }, { label: '输入指纹', value: <code>{run.input_fingerprint.slice(0, 12)}</code> }, { label: '阶段记录', value: run.stages.length }]} />
      {run.status === 'INTERRUPTED' && <InlineAlert tone="warning" title="任务在服务重启时中断">状态已经持久化，不会被误报为仍在运行；如有需要，可以从对应计划重新发起。</InlineAlert>}
      {run.downgrade_reasons.length > 0 && <InlineAlert tone="warning" title="任务发生降级">{run.downgrade_reasons.join('、')}</InlineAlert>}
      <section aria-label="任务阶段">
        <Panel density="compact" title="阶段历史" description="每次尝试按执行顺序保留，便于定位失败与恢复位置。">
          {run.stages.length === 0 ? <p className="status-detail">暂无阶段记录。</p> : <ol className="task-stage-list">{run.stages.map((stage) => <li key={`${stage.stage}-${stage.attempt_no}`}><span className="task-stage-list__index">{stage.attempt_no}</span><div><strong>{stage.stage}</strong><small>第 {stage.attempt_no} 次尝试{stage.error_code ? ` · ${stage.error_code}` : ''}</small></div><StatusBadge status={stage.status} /></li>)}</ol>}
        </Panel>
      </section>
      <Panel density="compact" title="任务事件" description="后端持久化的任务事件按时间显示。">{run.events.length === 0 ? <p className="status-detail">暂无任务事件。</p> : <ol className="task-event-list">{run.events.map((event, index) => <li key={`${event.event_type}-${event.created_at}-${index}`}><time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString('zh-CN')}</time><div><strong>{event.event_type}</strong><p>{event.summary}</p></div></li>)}</ol>}</Panel>
    </section>
  )
}
