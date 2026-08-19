import type { ShadowProgress, ShadowRunView } from '../shadowApi'

export default function ShadowAcceptanceCard({ runs, progress }: { runs: ShadowRunView[]; progress?: ShadowProgress }) {
  const passed = runs.filter((run) => run.status === 'PASSED').length
  return (
    <section className="card" aria-label="影子验收进度">
      <h3>Phase 3 影子验收</h3>
      <p>交易日进度：{progress?.trading_days ?? runs.length}/20</p>
      <p>通过：{progress?.passed ?? passed}</p>
      {progress && <p>剩余：{progress.remaining}，状态：{progress.complete ? '已完成' : '进行中'}</p>}
      {runs.length === 0 ? <p>尚未登记影子运行</p> : <ul>{runs.slice(0, 5).map((run) => <li key={run.shadow_id}>{run.trading_date}：{run.status}</li>)}</ul>}
    </section>
  )
}
