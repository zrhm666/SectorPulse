import { useCallback, useEffect, useState } from 'react'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import StatusBadge from '../components/ui/StatusBadge'
import { fetchOperationsSummary, type OperationsSummary } from '../operationsApi'
import { formatDate } from '../runPresentation'

export default function SystemStatusPage() {
  const [summary, setSummary] = useState<OperationsSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const load = useCallback(async () => {
    setLoading(true); setError(false)
    try { setSummary(await fetchOperationsSummary()) } catch { setError(true) } finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  return <section className="management-page">
    <PageHeader title="系统状态" description="仅显示可安全公开的连接和授权状态，不显示密钥、密码或连接串。" actions={<button className="button button-secondary" type="button" onClick={() => void load()}>刷新状态</button>} />
    {loading && <LoadingState label="正在加载系统状态…" />}
    {!loading && error && <InlineAlert tone="error" title="无法读取系统状态">请确认后端服务已启动后重试。</InlineAlert>}
    {!loading && !error && summary && <><p className="status-check-time">检查时间：{formatDate(summary.generated_at)}</p><section className="status-connection-grid" aria-label="系统连接状态">
      <Panel density="compact" title="数据库"><StatusBadge status="READY" label={summary.database.backend === 'postgresql' ? 'PostgreSQL 已连接' : 'SQLite 已连接'} /><p className="status-detail">数据库：{summary.database.name}</p></Panel>
      <Panel density="compact" title="LLM"><StatusBadge status={summary.llm.configured ? 'READY' : 'UNAVAILABLE'} label={summary.llm.configured ? '配置已就绪' : '配置不完整'} /><p className="status-detail">提供方：{summary.llm.provider}<br />模型：{summary.llm.model || '未设置'}<br />单次预算：¥{summary.llm.budget_cny_per_run}</p></Panel>
      <Panel density="compact" title="运行授权"><StatusBadge status={summary.providers.live_data_available ? 'READY' : 'UNAVAILABLE'} label={summary.providers.live_data_available ? '实时数据已就绪' : '实时数据不可用'} />{summary.providers.missing_requirements.map((item) => <p className="status-detail" key={item}>缺少 {item}</p>)}<p className="status-detail">实时 LLM 授权：{summary.consent.live_llm ? '已确认' : '未确认'}</p></Panel>
      <Panel density="compact" title="调度器"><StatusBadge status={summary.readiness.scheduler.status.toUpperCase()} label={summary.readiness.scheduler.label} /><p className="status-detail">{summary.readiness.scheduler.detail}</p></Panel>
    </section></>}
  </section>
}
