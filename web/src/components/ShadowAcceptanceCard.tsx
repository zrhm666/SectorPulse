import type { ShadowProgress, ShadowRunView } from '../shadowApi'
import SummaryStrip from './ui/SummaryStrip'

export default function ShadowAcceptanceCard({ runs, progress }: { runs: ShadowRunView[]; progress?: ShadowProgress }) {
  const passed = runs.filter((run) => run.status === 'PASSED').length
  const statusLabel = (status: string) => ({ PASSED: '通过', FAILED: '失败', BLOCKED: '阻塞' }[status] ?? status)
  return (
    <section aria-label="影子验收进度">
      <SummaryStrip label="验收指标" className="shadow-summary-strip" items={[{ label: '交易日进度', value: `${progress?.trading_days ?? runs.length}/20` }, { label: '通过', value: progress?.passed ?? passed }, { label: '失败 / 阻塞', value: progress ? `${progress.failed} / ${progress.blocked}` : '0 / 0' }, { label: '剩余', value: progress?.remaining ?? Math.max(0, 20 - runs.length) }]} />
      {runs.length === 0 ? <p className="status-detail">尚未登记影子运行。</p> : <div className="run-table-wrap"><table className="run-table" aria-label="影子运行历史"><thead><tr><th>交易日</th><th>模式</th><th>状态</th><th>运行编号</th><th>记录时间</th></tr></thead><tbody>{runs.map((run) => <tr key={run.shadow_id}><td data-label="交易日">{run.trading_date}</td><td data-label="模式">{run.mode === 'post_close' ? '盘后分析' : '盘中分析'}</td><td data-label="状态">{statusLabel(run.status)}</td><td data-label="运行编号"><code>{run.run_id.slice(0, 8)}</code></td><td data-label="记录时间">{new Date(run.created_at).toLocaleString('zh-CN')}</td></tr>)}</tbody></table></div>}
    </section>
  )
}
