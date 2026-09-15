import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

type TaskItem = {
  task_id: string; parent_id: string | null; role: string; scope: string
  attempt: number; status: string; worker_id: string | null
  lease_expires_at: string | null; public_error_code: string | null
  selection_version: number | null
}
type ArtifactRef = { artifact_id: string; task_id: string; kind: string; reference: string }
type ToolInvocation = {
  call_id: string; task_id: string; tool_name: string; status: string
  reserved_cny: string | null; actual_cny: string | null
}
type ModelCall = {
  call_id: string; task_id: string | null; role: string | null; model: string | null
  status: string | null; reserved_tokens: number; actual_tokens: number | null
  settled: boolean; reserved_cny: string | null; actual_cny: string | null
}
type Tasks = {
  recording: 'recorded' | 'not_recorded' | string
  tasks: TaskItem[]; artifacts: ArtifactRef[]
  tool_invocations: ToolInvocation[]; model_calls: ModelCall[]
  budget: Record<string, unknown>
}

const ROLE_LABELS: Record<string, string> = {
  A0: '调度', A1: '行情与候选', A2: '查证', A3: '写作', A4: '审校',
}
const STATUS_LABELS: Record<string, string> = {
  created: '待开始', running: '进行中', completed: '已完成', failed: '失败',
  cancelled: '已取消', interrupted: '已中断', waiting: '等待中',
  waiting_user_selection: '等待人工选择', waiting_user_review: '等待人工审核',
}
// The server publishes these codes; the UI never reinterprets a stop as success.
const STOP_LABELS: Record<string, string> = {
  AGENT_BUDGET_EXHAUSTED: '已达到运行预算限制', AGENT_TIME_LIMIT: '已达到查证时限',
  AGENT_TOOL_LIMIT: '已达到工具调用上限', AGENT_DECISION_LIMIT: '已达到决策轮次上限',
  AGENT_NO_PROGRESS: '重复查询，没有新进展', AGENT_CANCELLED: '查证已取消',
  AGENT_INVALID_CONCLUSION: '结论未通过证据校验', AGENT_INVALID_ACTION: '模型动作格式无效',
}
const ARTIFACT_VIEWS: Record<string, { tab: string; label: string }> = {
  sector_analysis: { tab: 'radar', label: '板块雷达' },
  candidate_selection: { tab: 'overview', label: '概览' },
  article_outline: { tab: 'draft', label: '草稿' },
  article_draft: { tab: 'draft', label: '草稿' },
  independent_review: { tab: 'review', label: '审核' },
  draft_rules: { tab: 'governance', label: '治理' },
}

function parseCents(value: string | null): number | null {
  if (value === null) return null
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value.trim())
  if (match === null) return null
  const [, sign, whole, fraction = ''] = match
  const cents = Number(whole) * 100 + Number(`${fraction}00`.slice(0, 2))
  return sign === '-' ? -cents : cents
}

type Spend = { toolCalls: number; modelCalls: number; settledCents: number; unknown: boolean }

function spendFor(taskId: string, tools: ToolInvocation[], models: ModelCall[]): Spend {
  const spend: Spend = { toolCalls: 0, modelCalls: 0, settledCents: 0, unknown: false }
  for (const call of tools) {
    if (call.task_id !== taskId) continue
    spend.toolCalls += 1
    const actual = parseCents(call.actual_cny)
    if (actual !== null) spend.settledCents += actual
    else if (parseCents(call.reserved_cny) !== null) spend.unknown = true
  }
  for (const call of models) {
    if (call.task_id !== taskId) continue
    spend.modelCalls += 1
    const actual = parseCents(call.actual_cny)
    if (call.settled && actual !== null) spend.settledCents += actual
    else if (parseCents(call.reserved_cny) !== null) spend.unknown = true
  }
  return spend
}

function TaskRow({ runId, task, tasks, artifacts, tools, models }: {
  runId: string; task: TaskItem; tasks: TaskItem[]; artifacts: ArtifactRef[]
  tools: ToolInvocation[]; models: ModelCall[]
}) {
  const role = ROLE_LABELS[task.role] ?? task.role
  const children = tasks.filter(item => item.parent_id === task.task_id)
  const spend = spendFor(task.task_id, tools, models)
  const views = new Map<string, { tab: string; label: string }>()
  for (const artifact of artifacts) {
    if (artifact.task_id !== task.task_id) continue
    const view = ARTIFACT_VIEWS[artifact.kind]
    if (view !== undefined) views.set(view.tab, view)
  }
  return <li>
    {/* The row is its own group so a parent's content never reads as its children's. */}
    <div className="task-row" role="group" aria-label={`${task.role} ${role} · ${task.scope}`}>
      <p className="task-row__head">
        <strong>{task.role}</strong>
        <span>{role}</span>
        <span className="task-row__scope">{task.scope}</span>
        <span>{STATUS_LABELS[task.status] ?? task.status}</span>
        {task.attempt > 1 && <span>第 {task.attempt} 次尝试</span>}
        {task.selection_version !== null && <span>选择版本 {task.selection_version}</span>}
        {task.lease_expires_at !== null && <span>租约至 {new Date(task.lease_expires_at).toLocaleString()}</span>}
        {task.public_error_code !== null && (
          <span>{STOP_LABELS[task.public_error_code] ?? `已停止：${task.public_error_code}`}</span>
        )}
      </p>
      <p className="task-row__spend">
        <span>工具 {spend.toolCalls} 次</span>
        <span>模型 {spend.modelCalls} 次</span>
        <span>{spend.unknown ? '费用未知' : `已结算 ¥${(spend.settledCents / 100).toFixed(2)}`}</span>
      </p>
      {views.size > 0 && <p className="task-row__artifacts">
        {[...views.values()].map(view => (
          <Link key={view.tab} to={`/runs/${runId}?tab=${view.tab}`}>{view.label}</Link>
        ))}
      </p>}
    </div>
    {children.length > 0 && (
      <ul aria-label={`${task.role} 子任务`}>
        {children.map(child => (
          <TaskRow key={child.task_id} runId={runId} task={child} tasks={tasks}
            artifacts={artifacts} tools={tools} models={models} />
        ))}
      </ul>
    )}
  </li>
}

export default function RunTaskTree({ runId, active }: { runId: string; active: boolean }) {
  const [snapshot, setSnapshot] = useState<{ runId: string; data: Tasks } | null>(null)
  const [error, setError] = useState(false)
  const [reload, setReload] = useState(0)
  const data = snapshot?.runId === runId ? snapshot.data : null

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    setError(false)
    const load = async () => {
      try {
        const result = await fetch(`/api/runs/${encodeURIComponent(runId)}/tasks`, { signal: controller.signal })
        if (!result.ok) throw new Error('tasks unavailable')
        const body = await result.json() as Tasks
        if (!Array.isArray(body.tasks)) throw new Error('invalid task tree')
        if (!controller.signal.aborted) { setSnapshot({ runId, data: body }); setError(false) }
      } catch {
        if (!controller.signal.aborted) setError(true)
      } finally {
        if (active && !controller.signal.aborted) timer = setTimeout(() => void load(), 2000)
      }
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [runId, active, reload])

  if (error) {
    return <div role="alert">任务树暂时无法加载。
      <button className="button button-secondary" onClick={() => setReload(value => value + 1)}>重新加载任务树</button>
    </div>
  }
  if (data === null) return <p>正在加载任务树…</p>

  const roots = data.tasks.filter(task => task.parent_id === null)
  return <section className="run-task-tree">
    <h3>任务树<small>{active ? '每 2 秒更新' : '已保存的执行记录'}</small></h3>
    {data.recording !== 'recorded' || roots.length === 0
      ? <p>{data.recording === 'recorded'
        ? '本次运行没有记录任务树。'
        : '本次运行没有记录任务树；未记录不等于未执行。'}</p>
      : <ul aria-label="任务树">
        {roots.map(task => (
          <TaskRow key={task.task_id} runId={runId} task={task} tasks={data.tasks}
            artifacts={data.artifacts} tools={data.tool_invocations} models={data.model_calls} />
        ))}
      </ul>}
  </section>
}
