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
  const attribution = events.filter(
    (event) => event.type === 'progress' && event.stage === 'attribution.progress',
  )
  const last = attribution[attribution.length - 1]

  return (
    <div>
      <p>{done ? '运行已结束。' : '运行正在执行，阶段状态会自动更新。'}</p>
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
