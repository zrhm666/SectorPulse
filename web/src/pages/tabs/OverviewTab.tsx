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
  const labels: Record<string, string> = { 'phase1b.start': '启动', 'attribution.start': '归因开始', 'attribution.done': '归因完成', 'editorial.done': '编辑完成', 'writing.done': '写作完成', 'review.done': '审核完成' }
  const historicalComplete = done && run?.status === 'READY_FOR_HUMAN_REVIEW'
  const failed = done && run?.status === 'FAILED'
  return (
    <div>
      <p>{done ? '运行已结束。' : '运行正在执行，阶段状态会自动更新。'}</p>
      <ol className="timeline">
        {stages.map((s) => { const complete = seen.has(s) || historicalComplete; return <li key={s} data-complete={complete}><span aria-hidden="true" /><strong>{labels[s]}</strong><small>{complete ? '已完成' : failed ? '未完成' : '等待中'}</small></li> })}
      </ol>
      {last && (
        <p>
          归因进度：{String(last.detail?.done)} / {String(last.detail?.total)}
        </p>
      )}
      {run?.status === 'READY_FOR_HUMAN_REVIEW' && <p>草稿已就绪，请切换到“草稿”查看并审核。</p>}
    </div>
  )
}
