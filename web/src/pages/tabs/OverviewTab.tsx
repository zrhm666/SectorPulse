import { RunSummary } from '../../api'
import { ProgressEvent } from '../../useRuns'

type StageState = 'complete' | 'degraded' | 'failed' | 'skipped' | 'pending'

const stages = [
  'phase1b.start',
  'attribution.start',
  'attribution.done',
  'editorial.done',
  'writing.done',
  'review.done',
] as const

const labels: Record<(typeof stages)[number], string> = {
  'phase1b.start': '启动',
  'attribution.start': '归因开始',
  'attribution.done': '归因完成',
  'editorial.done': '编辑完成',
  'writing.done': '写作完成',
  'review.done': '审核完成',
}

const stateLabels: Record<StageState, string> = {
  complete: '已完成',
  degraded: '已降级完成',
  failed: '失败',
  skipped: '未执行',
  pending: '等待中',
}

function resolveStageStates(
  events: ProgressEvent[],
  done: boolean,
  status: string | undefined,
): StageState[] {
  const seen = new Set(events.map((event) => event.stage))
  if (status === 'READY_FOR_HUMAN_REVIEW') {
    return stages.map(() => 'complete')
  }
  if (status === 'DRAFT_GENERATION_FAILED') {
    return ['complete', 'complete', 'complete', seen.has('editorial.fallback') ? 'degraded' : 'complete', 'failed', 'skipped']
  }

  const failedIndex = seen.has('writing.failed') ? 4 : -1
  const observedIndexes = stages
    .map((stage, index) => (seen.has(stage) ? index : -1))
    .filter((index) => index >= 0)
  if (seen.has('editorial.fallback')) observedIndexes.push(3)
  if (failedIndex >= 0) observedIndexes.push(failedIndex)
  const furthestObserved = Math.max(-1, ...observedIndexes)

  return stages.map((stage, index) => {
    if (index === 3 && seen.has('editorial.fallback')) return 'degraded'
    if (index === failedIndex) return 'failed'
    if (seen.has(stage) || index < furthestObserved) return 'complete'
    if (failedIndex >= 0 && index > failedIndex) return 'skipped'
    if (done) return 'skipped'
    return 'pending'
  })
}

export default function OverviewTab({
  events,
  done,
  run,
}: {
  events: ProgressEvent[]
  done: boolean
  run: RunSummary | null
}) {
  const attribution = events.filter(
    (event) => event.type === 'progress' && event.stage === 'attribution.progress',
  )
  const last = attribution[attribution.length - 1]
  const states = resolveStageStates(events, done, run?.status)

  return (
    <div>
      <p>{done ? '运行已结束。' : '运行正在执行，阶段状态会自动更新。'}</p>
      <ol className="timeline">
        {stages.map((stage, index) => (
          <li key={stage} data-state={states[index]}>
            <span aria-hidden="true" />
            <strong>{labels[stage]}</strong>
            <small data-testid="timeline-state">{stateLabels[states[index]]}</small>
          </li>
        ))}
      </ol>
      {last && (
        <p>
          归因进度：{String(last.detail?.done)} / {String(last.detail?.total)}
        </p>
      )}
      {run?.status === 'READY_FOR_HUMAN_REVIEW' && (
        <p>草稿已就绪，请切换到“草稿”查看并审核。</p>
      )}
    </div>
  )
}
