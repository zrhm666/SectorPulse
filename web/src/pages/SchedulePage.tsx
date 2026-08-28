import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import EmptyState from '../components/ui/EmptyState'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import SummaryStrip from '../components/ui/SummaryStrip'
import { useFeedback } from '../components/ui/FeedbackProvider'
import { createSchedule, fetchSchedules, type NewScheduleInput, type ScheduleView, triggerSchedule } from '../schedulesApi'
import ManagementDrawer from '../components/ui/ManagementDrawer'

const initialForm: NewScheduleInput = { name: '', mode: 'post_close', timezone: 'Asia/Shanghai', local_time: '16:00', trading_days: 'weekdays', enabled: true, input_template: {} }

export default function SchedulePage() {
  const [schedules, setSchedules] = useState<ScheduleView[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [creating, setCreating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [triggering, setTriggering] = useState<string | null>(null)
  const [form, setForm] = useState<NewScheduleInput>(initialForm)
  const navigate = useNavigate()
  const feedback = useFeedback()

  const load = useCallback(() => {
    let active = true
    setLoading(true)
    setLoadError(false)
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

    return () => { active = false }
  }, [])

  useEffect(() => load(), [load])

  const trigger = async (scheduleId: string) => {
    setTriggering(scheduleId)
    try {
      const result = await triggerSchedule(scheduleId)
      navigate(`/task-runs/${result.run_id}`)
    } catch {
      feedback.error('计划触发失败，请稍后重试。')
    } finally {
      setTriggering(null)
    }
  }

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    setSaving(true)
    try {
      const schedule = await createSchedule(form)
      setSchedules((items) => [...items, schedule])
      setForm(initialForm)
      setCreating(false)
      feedback.success('调度计划已创建。')
    } catch {
      feedback.error('计划创建失败，请检查输入后重试。')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="management-page">
      <PageHeader title="定时任务" description="统一创建、查看和手动触发盘中与盘后分析计划。" actions={<button className="button button-primary" type="button" onClick={() => setCreating(true)}>新建计划</button>} />
      <SummaryStrip label="调度概览" items={[{ label: '计划总数', value: schedules.length }, { label: '启用中', value: schedules.filter((item) => item.enabled).length }, { label: '默认时区', value: 'Asia/Shanghai' }]} />
      <ManagementDrawer open={creating} title="新建调度计划" description="按计划所在时区解释执行时间。" onClose={() => setCreating(false)}><form className="schedule-form" onSubmit={save}><label>计划名称<input required value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} /></label><label>分析模式<select value={form.mode} onChange={(event) => setForm((current) => ({ ...current, mode: event.target.value }))}><option value="post_close">盘后分析</option><option value="intraday">盘中分析</option></select></label><label>执行时区<select value={form.timezone} onChange={(event) => setForm((current) => ({ ...current, timezone: event.target.value }))}><option value="Asia/Shanghai">Asia/Shanghai</option><option value="UTC">UTC</option></select></label><label>执行时间<input type="time" required value={form.local_time} onInput={(event) => { const localTime = event.currentTarget.value; setForm((current) => ({ ...current, local_time: localTime })) }} /></label><label>交易日<select value={form.trading_days} onChange={(event) => setForm((current) => ({ ...current, trading_days: event.target.value }))}><option value="weekdays">工作日</option><option value="daily">每天</option></select></label><label className="schedule-form__check"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm((current) => ({ ...current, enabled: event.target.checked }))} />创建后立即启用</label><div className="schedule-form__actions"><button className="button button-secondary" type="button" onClick={() => setCreating(false)}>取消</button><button className="button button-primary" type="submit" disabled={saving}>{saving ? '正在保存…' : '保存计划'}</button></div></form></ManagementDrawer>
      <Panel density="compact" title="调度计划" description="时间按每项计划标明的时区执行。">
        {loading && <LoadingState label="正在加载调度计划…" />}
        {!loading && loadError && (
          <InlineAlert tone="error" title="无法加载调度计划"><p>请确认服务可用后重试。</p><button className="button button-secondary" type="button" onClick={load}>重新加载</button></InlineAlert>
        )}
        {!loading && !loadError && schedules.length === 0 && (
          <EmptyState title="还没有调度计划" description="当前没有可运行的定时任务。" />
        )}
        {!loading && !loadError && schedules.length > 0 && (
          <div className="run-table-wrap"><table className="run-table" aria-label="调度计划"><thead><tr><th>名称</th><th>模式</th><th>时间与时区</th><th>下一次触发</th><th>状态</th><th>操作</th></tr></thead><tbody>{schedules.map((schedule) => <tr key={schedule.schedule_id}><td data-label="名称"><strong>{schedule.name}</strong></td><td data-label="模式">{schedule.mode === 'post_close' ? '盘后分析' : '盘中分析'}</td><td data-label="时间与时区">{schedule.local_time} · {schedule.timezone}</td><td data-label="下一次触发">{schedule.next_run_at ?? '未计算'}</td><td data-label="状态">{schedule.enabled ? '已启用' : '已停用'}</td><td data-label="操作"><button className="button button-secondary" type="button" disabled={triggering === schedule.schedule_id} onClick={() => trigger(schedule.schedule_id)}>{triggering === schedule.schedule_id ? '正在触发…' : '立即运行'}</button></td></tr>)}</tbody></table></div>
        )}
      </Panel>
    </section>
  )
}
