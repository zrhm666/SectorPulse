import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchTaskRun, TaskRunView } from '../schedulesApi'

export default function TaskRunPage() {
  const { runId } = useParams()
  const [run, setRun] = useState<TaskRunView | null>(null)

  useEffect(() => {
    if (runId) fetchTaskRun(runId).then(setRun).catch(console.error)
  }, [runId])

  if (!run) return <p>加载任务…</p>

  return (
    <section>
      <h1>任务 {run.run_id.slice(0, 8)}</h1>
      <p>状态：{run.status}</p>
      <h2>阶段历史</h2>
      <ul>
        {run.stages.map((stage) => (
          <li key={`${stage.stage}-${stage.attempt_no}`}>
            {stage.stage} / attempt {stage.attempt_no} / {stage.status}
            {stage.error_code ? `（${stage.error_code}）` : ''}
          </li>
        ))}
      </ul>
      {run.downgrade_reasons.length > 0 && (
        <p>降级原因：{run.downgrade_reasons.join('、')}</p>
      )}
      <button type="button">重试</button>
      <button type="button">恢复</button>
    </section>
  )
}
