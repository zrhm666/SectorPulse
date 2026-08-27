import { Link } from 'react-router-dom'

import type { DataRunContentView, DataRunView } from '../../dataRunsApi'

const RETRYABLE = new Set(['DEGRADED', 'BLOCKED', 'FAILED', 'CANCELLED', 'INTERRUPTED'])

type Props = {
  run: DataRunView
  contentRun: DataRunContentView | null
  busy: boolean
  error: string | null
  candidateCount: number
  candidatesLoading: boolean
  selectionConfirmed?: boolean
  selectionDirty?: boolean
  onGenerate: () => void
  onRetry: () => void
}

export default function DataRunActionPanel({ run, contentRun, busy, error, candidateCount, candidatesLoading, selectionConfirmed = true, selectionDirty = false, onGenerate, onRetry }: Props) {
  let action
  let description = '数据采集完成后，可从这里继续生成分析稿。'
  if (contentRun) {
    const label = contentRun.can_view_draft ? '查看分析稿' : '查看生成进度'
    description = `内容运行状态：${contentRun.status}`
    action = <Link className="button button-primary" to={`/runs/${contentRun.run_id}`}>{label}</Link>
  } else if (run.status === 'READY_FOR_ATTRIBUTION') {
    const selectionReady = !candidatesLoading && candidateCount >= 3 && selectionConfirmed && !selectionDirty
    description = candidatesLoading
      ? '正在加载候选板块，加载完成后可以确认写作范围。'
      : candidateCount < 3
        ? '请在下方候选板块中至少选择 3 个板块。'
        : !selectionConfirmed
          ? '请先确认候选板块版本，再生成分析稿。'
          : selectionDirty
            ? '候选范围有未确认修改，请保存后再生成分析稿。'
            : `已确认 ${candidateCount} 个候选板块，分析稿只会覆盖该版本。`
    action = <button className="button button-primary" type="button" disabled={busy || !selectionReady} onClick={onGenerate}>{busy ? '正在启动生成…' : '生成分析稿'}</button>
  } else if (RETRYABLE.has(run.status)) {
    description = run.error_code ? `本次运行未能继续：${run.error_code}` : '本次运行未能继续，可按原参数重新采集。'
    action = <button className="button button-primary" type="button" disabled={busy} onClick={onRetry}>{busy ? '正在创建新运行…' : '按原参数重新采集'}</button>
  } else {
    action = <button className="button button-secondary" type="button" disabled>等待数据就绪</button>
  }
  return (
    <section className="data-run-action" aria-label="下一步操作">
      <div>
        <strong>下一步</strong>
        <p>{description}</p>
        {error && <p className="data-run-action__error" role="alert">{error}</p>}
      </div>
      {action}
    </section>
  )
}
