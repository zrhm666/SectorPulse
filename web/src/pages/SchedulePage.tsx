import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchSchedules, ScheduleView, triggerSchedule } from '../schedulesApi'

export default function SchedulePage() {
  const [schedules, setSchedules] = useState<ScheduleView[]>([])
  const navigate = useNavigate()

  useEffect(() => {
    fetchSchedules().then(setSchedules).catch(console.error)
  }, [])

  const trigger = async (scheduleId: string) => {
    const result = await triggerSchedule(scheduleId)
    navigate(`/task-runs/${result.run_id}`)
  }

  return (
    <section>
      <h1>调度计划</h1>
      {schedules.map((schedule) => (
        <article className="card" key={schedule.schedule_id}>
          <strong>{schedule.name}</strong>
          <p>{schedule.mode} · {schedule.timezone} · {schedule.local_time}</p>
          <p>下一次触发：{schedule.next_run_at ?? '未计算'}</p>
          <button onClick={() => trigger(schedule.schedule_id)}>立即运行</button>
        </article>
      ))}
    </section>
  )
}
