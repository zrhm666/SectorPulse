import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import EmptyState from '../components/ui/EmptyState'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import { fetchSchedules, type ScheduleView, triggerSchedule } from '../schedulesApi'

export default function SchedulePage() {
  const [schedules, setSchedules] = useState<ScheduleView[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    let active = true

    fetchSchedules()
      .then((result) => {
        if (active) setSchedules(result)
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

  const trigger = async (scheduleId: string) => {
    const result = await triggerSchedule(scheduleId)
    navigate(`/task-runs/${result.run_id}`)
  }

  return (
    <section>
      <PageHeader title="定时任务" description="查看现有调度计划，并按需立即触发一次运行。" />
      <Panel title="调度计划" description="时间按每项计划标明的时区执行。">
        {loading && <LoadingState label="正在加载调度计划…" />}
        {!loading && loadError && (
          <InlineAlert tone="error" title="无法加载调度计划">请稍后刷新页面重试。</InlineAlert>
        )}
        {!loading && !loadError && schedules.length === 0 && (
          <EmptyState title="还没有调度计划" description="当前没有可运行的定时任务。" />
        )}
        {!loading && !loadError && schedules.length > 0 && (
          <ul aria-label="调度计划">
            {schedules.map((schedule) => (
              <li className="card" key={schedule.schedule_id}>
                <article>
                  <h3>{schedule.name}</h3>
                  <p>{schedule.mode} · {schedule.timezone} · {schedule.local_time}</p>
                  <p>下一次触发：{schedule.next_run_at ?? '未计算'}</p>
                  <button className="button button-primary" type="button" onClick={() => trigger(schedule.schedule_id)}>立即运行</button>
                </article>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </section>
  )
}
