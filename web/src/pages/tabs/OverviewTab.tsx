// web/src/pages/tabs/OverviewTab.tsx
import { RunSummary } from '../../api'
import { ProgressEvent } from '../../useRuns'

export default function OverviewTab({
  events,
  done,
  run,
}: {
  events: ProgressEvent[]
  done: boolean
  run: RunSummary | null
}) {
  const stages = [
    'phase1b.start',
    'attribution.start',
    'attribution.done',
    'editorial.done',
    'writing.done',
    'review.done',
  ]
  const seen = new Set(events.map((e) => e.stage))
  const attribution = events.filter(
    (e) => e.type === 'progress' && e.stage === 'attribution.progress',
  )
  const last = attribution[attribution.length - 1]
  return (
    <div>
      {!done && <p>运行中… SSE 阶段进度如下：</p>}
      {done && <p>运行已结束。</p>}
      <ul>
        {stages.map((s) => (
          <li key={s} style={{ color: seen.has(s) ? '#0f9d58' : '#9aa0a6' }}>
            {seen.has(s) ? '✓' : '○'} {s}
          </li>
        ))}
      </ul>
      {last && (
        <p>
          归因进度：{String(last.detail?.done)} / {String(last.detail?.total)}
        </p>
      )}
      {run?.status === 'READY_FOR_HUMAN_REVIEW' && <p>草案已就绪，请切换到「草案」标签查看。</p>}
    </div>
  )
}