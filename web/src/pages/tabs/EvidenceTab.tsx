// web/src/pages/tabs/EvidenceTab.tsx
import { useEffect, useState } from 'react'
import { fetchEvidence } from '../../api'

interface NewsDocument {
  title: string
  citation_url: string | null
  publisher: string | null
}

interface NewsEvent {
  event_id: string
  canonical_title: string
  documents: NewsDocument[]
}

interface Invocation {
  stage: string
  model: string
  prompt_id: string
  prompt_version: number
  status: string
  total_tokens: number
  estimated_cost_cny: number
}

interface EvidenceData {
  sectors: unknown[]
  events: NewsEvent[]
  invocations: Invocation[]
}

export default function EvidenceTab({ runId }: { runId: string }) {
  const [data, setData] = useState<EvidenceData>({ sectors: [], events: [], invocations: [] })
  useEffect(() => {
    fetchEvidence(runId).then((d) => setData(d as EvidenceData)).catch(console.error)
  }, [runId])

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
              <a href={d.citation_url ?? '#'} target="_blank" rel="noreferrer">
                {d.title}
              </a>
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