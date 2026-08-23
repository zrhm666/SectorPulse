import type { ShadowProgress, ShadowRunView } from '../shadowApi'

export default function ShadowAcceptanceCard({ runs, progress }: { runs: ShadowRunView[]; progress?: ShadowProgress }) {
  const passed = runs.filter((run) => run.status === 'PASSED').length
  const statusLabel = (status: string) => ({ PASSED: '通过', FAILED: '失败', BLOCKED: '阻塞' }[status] ?? status)
  return (
    <section aria-label="影子验收进度">
      <div className="shadow-summary"><div><span>交易日进度</span><strong>交易日进度：{progress?.trading_days ?? runs.length}/20</strong></div><div><span>通过</span><strong>{progress?.passed ?? passed}</strong></div><div><span>失败 / 阻塞</span><strong>{progress ? `${progress.failed} / ${progress.blocked}` : '0 / 0'}</strong></div><div><span>剩余</span><strong>{progress?.remaining ?? Math.max(0, 20 - runs.length)}</strong></div></div>
      {runs.length === 0 ? <p className="status-detail">尚未登记影子运行。</p> : <div className="run-table-wrap"><table className="run-table" aria-label="影子运行历史"><thead><tr><th>交易日</th><th>模式</th><th>状态</th><th>运行编号</th><th>记录时间</th></tr></thead><tbody>{runs.map((run) => <tr key={run.shadow_id}><td data-label="交易日">{run.trading_date}</td><td data-label="模式">{run.mode === 'post_close' ? '盘后分析' : '盘中分析'}</td><td data-label="状态">{statusLabel(run.status)}</td><td data-label="运行编号"><code>{run.run_id.slice(0, 8)}</code></td><td data-label="记录时间">{new Date(run.created_at).toLocaleString('zh-CN')}</td></tr>)}</tbody></table></div>}
    </section>
  )
}
