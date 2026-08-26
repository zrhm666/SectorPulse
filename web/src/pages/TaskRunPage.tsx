import { useEffect, useState } from 'react'
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

  useEffect(() => {
    if (runId) fetchTaskRun(runId).then(setRun).catch(console.error)
  }, [runId])

  if (!run) return <LoadingState label="正在加载任务…" />

  return (
    <section className="management-page task-run-page">
      <PageHeader title={`任务 ${run.run_id.slice(0, 8)}`} description="查看调度任务状态、阶段尝试与降级信息。" actions={<div className="task-run-actions"><button className="button button-secondary" type="button">重试</button><button className="button button-primary" type="button">恢复</button></div>} />
      <SummaryStrip label="任务摘要" items={[{ label: '状态', value: <StatusBadge status={run.status} /> }, { label: 'Provider', value: run.provider }, { label: '输入指纹', value: <code>{run.input_fingerprint.slice(0, 12)}</code> }, { label: '阶段记录', value: run.stages.length }]} />
      {run.downgrade_reasons.length > 0 && <InlineAlert tone="warning" title="任务发生降级">{run.downgrade_reasons.join('、')}</InlineAlert>}
      <section aria-label="任务阶段">
        <Panel density="compact" title="阶段历史" description="每次尝试按执行顺序保留，便于定位失败与恢复位置。">
          {run.stages.length === 0 ? <p className="status-detail">暂无阶段记录。</p> : <ol className="task-stage-list">{run.stages.map((stage) => <li key={`${stage.stage}-${stage.attempt_no}`}><span className="task-stage-list__index">{stage.attempt_no}</span><div><strong>{stage.stage}</strong><small>第 {stage.attempt_no} 次尝试{stage.error_code ? ` · ${stage.error_code}` : ''}</small></div><StatusBadge status={stage.status} /></li>)}</ol>}
        </Panel>
      </section>
    </section>
  )
}
