import type { DataRunView } from '../../dataRunsApi'

type StageState = 'complete' | 'running' | 'waiting' | 'degraded' | 'failed' | 'cancelled' | 'interrupted' | 'skipped'

const STAGES = [
  { status: 'FETCHING_MARKET', label: '行情采集' },
  { status: 'RANKING_PRE_CANDIDATES', label: '预候选排序' },
  { status: 'FETCHING_NEWS', label: '新闻采集' },
  { status: 'BUILDING_EVIDENCE', label: '证据构建' },
  { status: 'READY_FOR_ATTRIBUTION', label: '归因就绪' },
] as const

const STATE_LABEL: Record<StageState, string> = {
  complete: '已完成',
  running: '进行中',
  waiting: '等待中',
  degraded: '已降级',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断',
  skipped: '未执行',
}

function terminalStates(run: DataRunView): StageState[] {
  if (run.status === 'READY_FOR_ATTRIBUTION') return STAGES.map(() => 'complete')
  if (run.status === 'DEGRADED') return ['complete', 'complete', 'complete', 'complete', 'degraded']
  if (run.status === 'BLOCKED') return ['complete', 'complete', 'complete', 'complete', 'failed']
  const outcome: StageState = run.status === 'CANCELLED'
    ? 'cancelled'
    : run.status === 'INTERRUPTED' ? 'interrupted' : 'failed'
  const completed = run.cutoff_at ? 1 : 0
  return STAGES.map((_, index) => index < completed ? 'complete' : index === completed ? outcome : 'skipped')
}

export function resolveDataRunStages(run: DataRunView): StageState[] {
  if (['READY_FOR_ATTRIBUTION', 'DEGRADED', 'BLOCKED', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(run.status)) {
    return terminalStates(run)
  }
  const current = STAGES.findIndex((stage) => stage.status === run.status)
  if (current < 0) return STAGES.map(() => 'waiting')
  return STAGES.map((_, index) => index < current ? 'complete' : index === current ? 'running' : 'waiting')
}

export default function DataRunTimeline({ run }: { run: DataRunView }) {
  const states = resolveDataRunStages(run)
  return (
    <ol className="timeline timeline--five">
      {STAGES.map((stage, index) => (
        <li key={stage.status} data-state={states[index]}>
          <span aria-hidden="true" />
          <strong>{stage.label}</strong>
          <small data-testid="data-run-stage-state">{STATE_LABEL[states[index]]}</small>
        </li>
      ))}
    </ol>
  )
}
