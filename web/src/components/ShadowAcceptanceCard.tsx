import type { ShadowRunView } from '../shadowApi'

export default function ShadowAcceptanceCard({ runs }: { runs: ShadowRunView[] }) {
  const passed = runs.filter((run) => run.status === 'PASSED').length
  return (
    <section className="card" aria-label="影子验收进度">
      <h3>Phase 3 影子验收</h3>
      <p>交易日进度：{runs.length}/20</p>
      <p>通过：{passed}</p>
      {runs.length === 0 ? <p>尚未登记影子运行</p> : <ul>{runs.slice(0, 5).map((run) => <li key={run.shadow_id}>{run.trading_date}：{run.status}</li>)}</ul>}
    </section>
  )
}
