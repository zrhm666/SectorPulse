import type { RunSummary } from '../../api'
import type { ProgressEvent } from '../../useRuns'

type StageState = 'complete' | 'degraded' | 'failed' | 'skipped' | 'pending' | 'unknown'

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
  'review.done': '自动审核完成',
}

const stateLabels: Record<StageState, string> = {
  complete: '已完成',
  degraded: '已降级完成',
  failed: '失败',
  skipped: '未执行',
  pending: '等待中',
  unknown: '未记录',
}

function resolveStageStates(events: ProgressEvent[], done: boolean, run: RunSummary | null, hasAttribution: boolean): StageState[] {
  const status = run?.status
  const seen = new Set(events.map((event) => event.stage))
  if (status === 'READY_FOR_HUMAN_REVIEW') return stages.map(() => 'complete')
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
    // Saved artifacts prove their own stage, not every earlier stage or a passing review.
    if (index === 0 && (run?.draft_id || hasAttribution)) return 'complete'
    if ((index === 1 || index === 2) && hasAttribution) return 'complete'
    if (index === 4 && run?.draft_id) return 'complete'
    if (index === 5 && run?.review_decision) return 'complete'
    if (done) return 'unknown'
    return 'pending'
  })
}

export default function ContentRunStageRail({ events, done, run, hasAttribution = false }: { events: ProgressEvent[]; done: boolean; run: RunSummary | null; hasAttribution?: boolean }) {
  const states = resolveStageStates(events, done, run, hasAttribution)
  return <section className="content-run-stage-rail" role="region" aria-label="运行阶段">
    <div className="content-run-stage-rail__heading">
      <strong>运行阶段</strong>
      <span>{done ? '运行已结束' : '阶段状态会自动更新'}</span>
    </div>
    <ol className="timeline">
      {stages.map((stage, index) => <li key={stage} data-state={states[index]}>
        <span aria-hidden="true" />
        <strong>{labels[stage]}</strong>
        <small data-testid="timeline-state">{stateLabels[states[index]]}</small>
      </li>)}
    </ol>
    {done && states.includes('unknown') && <p className="status-detail">历史进度记录不完整；已保存的产物用于确认对应阶段，“未记录”不代表未执行。自动审核完成也不代表已人工批准。</p>}
  </section>
}
