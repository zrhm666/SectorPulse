// web/src/pages/tabs/EvidenceTab.tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { EvidenceView, fetchEvidence } from '../../api'
import InlineAlert from '../../components/ui/InlineAlert'
import LoadingState from '../../components/ui/LoadingState'

export default function EvidenceTab({ runId }: { runId: string }) {
  const [data, setData] = useState<EvidenceView>({ sectors: [], events: [], invocations: [] })
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const requestId = useRef(0)
  const load = useCallback(async () => {
    const currentRequest = ++requestId.current
    setLoading(true)
    setLoadError(false)
    try {
      const evidence = await fetchEvidence(runId)
      if (currentRequest === requestId.current) setData(evidence)
    } catch {
      if (currentRequest === requestId.current) setLoadError(true)
    } finally {
      if (currentRequest === requestId.current) setLoading(false)
    }
  }, [runId])
  useEffect(() => {
    void load()
    return () => { requestId.current += 1 }
  }, [load])

  if (loading) return <LoadingState label="正在加载证据与调用审计…" />
  if (loadError) return <InlineAlert tone="error" title="无法加载证据与调用审计"><button className="button button-secondary" type="button" onClick={() => void load()}>重新加载</button></InlineAlert>

  return (
    <div>
      <h3>新闻事件</h3>
      {data.events.length === 0 && <p>暂无关联新闻事件。</p>}
      {data.events.map((ev) => (
        <div key={ev.event_id} className="card">
          <p>
            <strong>{ev.canonical_title}</strong>
          </p>
          {ev.documents.map((d, i) => (
            <p key={i}>
              {d.citation_url
                ? <a href={d.citation_url} target="_blank" rel="noreferrer">{d.title}</a>
                : <span>{d.title}</span>}
              {d.publisher ? `（${d.publisher}）` : ''}
            </p>
          ))}
        </div>
      ))}
      <h3>调用审计</h3>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            <th style={{ border: '1px solid #ddd', padding: 4 }}>阶段</th>
            <th style={{ border: '1px solid #ddd', padding: 4 }}>模型</th>
            <th style={{ border: '1px solid #ddd', padding: 4 }}>Prompt</th>
            <th style={{ border: '1px solid #ddd', padding: 4 }}>状态</th>
            <th style={{ border: '1px solid #ddd', padding: 4 }}>Token</th>
            <th style={{ border: '1px solid #ddd', padding: 4 }}>成本</th>
          </tr>
        </thead>
        <tbody>
          {data.invocations.map((inv, i) => (
            <tr key={i}>
              <td style={{ border: '1px solid #ddd', padding: 4 }}>{inv.stage}</td>
              <td style={{ border: '1px solid #ddd', padding: 4 }}>{inv.model}</td>
              <td style={{ border: '1px solid #ddd', padding: 4 }}>
                {inv.prompt_id}@{inv.prompt_version}
              </td>
              <td style={{ border: '1px solid #ddd', padding: 4 }}>{inv.status}</td>
              <td style={{ border: '1px solid #ddd', padding: 4 }}>{inv.total_tokens}</td>
              <td style={{ border: '1px solid #ddd', padding: 4 }}>¥{inv.estimated_cost_cny}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
