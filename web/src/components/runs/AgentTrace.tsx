import { useEffect, useState } from 'react'

type Step = {
  sector_id: string; sector_kind: string; step: number; recorded_at: string
  event: {
    type: string; sector_name?: string; reason?: string
    action?: { action: string; query?: string; document_id?: string }
    observation?: { status: string; error_code?: string; data?: {
      availability?: string; content?: string; documents?: Array<{ document_id: string; title: string; summary?: string }>
    } }
  }
}
const ACTIONS: Record<string, string> = {
  search_news: '检索新闻', read_news_detail: '阅读新闻详情', inspect_market: '核对锁定行情',
}
const STOPS: Record<string, string> = {
  AGENT_BUDGET_EXHAUSTED: '已达到运行预算限制', AGENT_TIME_LIMIT: '已达到查证时限',
  AGENT_TOOL_LIMIT: '已达到工具调用上限', AGENT_DECISION_LIMIT: '已达到决策轮次上限',
  AGENT_NO_PROGRESS: '重复查询，没有新进展', AGENT_CANCELLED: '查证已取消',
  AGENT_INVALID_CONCLUSION: '结论未通过证据校验', AGENT_INVALID_ACTION: '模型动作格式无效',
}

export default function AgentTrace({ runId, active }: { runId: string; active: boolean }) {
  const [snapshot, setSnapshot] = useState<{ runId: string; steps: Step[] } | null>(null)
  const [error, setError] = useState(false)
  const [reload, setReload] = useState(0)
  const steps = snapshot?.runId === runId ? snapshot.steps : []
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    setError(false)
    const load = async () => {
      try {
        const result = await fetch(`/api/runs/${encodeURIComponent(runId)}/agent-trace`, { signal: controller.signal })
        if (!result.ok) throw new Error('trace unavailable')
        const body = await result.json() as { steps: Step[] }
        if (!Array.isArray(body.steps)) throw new Error('invalid trace')
        if (!controller.signal.aborted) { setSnapshot({ runId, steps: body.steps }); setError(false) }
      } catch {
        if (!controller.signal.aborted) setError(true)
      } finally {
        if (active && !controller.signal.aborted) timer = setTimeout(() => void load(), 2000)
      }
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [runId, active, reload])
  const groups = new Map<string, Step[]>()
  for (const step of steps) {
    const key = `${step.sector_kind}:${step.sector_id}`
    groups.set(key, [...(groups.get(key) ?? []), step])
  }
  return <details className="agent-trace" open>
    <summary><strong>Agent 查证记录</strong><span>{active ? '每 2 秒更新' : '已保存的执行记录'} · {groups.size} 个板块</span></summary>
    <p>仅展示工具动作与可核对的结果。后来读取的原文不代表数据截止时已知的事实。</p>
    {error && <div role="alert">查证记录暂时无法加载。<button className="button button-secondary" onClick={() => setReload(value => value + 1)}>重新加载记录</button></div>}
    {!error && !steps.length && <p>{active ? '等待首条查证记录…' : '本次运行没有保存的查证记录。'}</p>}
    {[...groups].map(([key, entries]) => {
      const name = entries.find(step => step.event.sector_name)?.event.sector_name
      return <section className="agent-trace__sector" key={key}>
        <h3>{name || entries[0].sector_id} · {entries[0].sector_kind === 'INDUSTRY' ? '行业' : '概念'}</h3>
        <ol>{entries.filter(step => step.event.type !== 'started' && step.event.type !== 'tool_started').map(step => {
          const event = step.event
          const data = event.observation?.data
          return <li key={`${step.step}:${event.type}`}>
            <strong>{event.type === 'finished' ? '归因结论已通过校验' : event.type === 'stopped'
              ? STOPS[event.reason ?? ''] ?? `查证已停止：${event.reason ?? '原因未记录'}`
              : ACTIONS[event.action?.action ?? ''] ?? '工具结果'}</strong>
            {event.action?.query && <span> · {event.action.query}</span>}
            {event.observation && <span> · {({ success: '已返回', partial: '部分可用', unavailable: '暂无可用结果', error: '执行失败' } as Record<string, string>)[event.observation.status] ?? event.observation.status}</span>}
            {data?.availability && <p>{data.availability === 'full_text' ? '已读取正文（不等于已验证事实）' : data.availability === 'summary_only' ? '仅有摘要，未读取完整原文' : '原文不可用'}</p>}
            {data?.content && <details><summary>查看保存的内容</summary><p className="agent-trace__detail">{data.content}</p></details>}
            {data?.documents?.map(doc => <p key={doc.document_id}>{doc.title}{doc.summary && ` — ${doc.summary}`}</p>)}
            {event.observation?.error_code && <p>原因：{event.observation.error_code}</p>}
          </li>
        })}</ol>
        {active && entries[entries.length - 1]?.event.type === 'tool_started' && <p>正在{ACTIONS[entries[entries.length - 1]?.event.action?.action ?? ''] ?? '调用工具'}…</p>}
      </section>
    })}
  </details>
}
