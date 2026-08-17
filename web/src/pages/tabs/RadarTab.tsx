// web/src/pages/tabs/RadarTab.tsx
import { useEffect, useState } from 'react'
import { fetchRadar } from '../../api'
import Badge from '../../components/Badge'

interface RadarCard {
  sector_id: string
  attribution_level: string
  confidence: number
  allowed_max_level: string
  conclusion: string
  counter_evidence: string[]
  uncertainties: string[]
  claims: { claim_id: string; text: string }[]
}

export default function RadarTab({ runId }: { runId: string }) {
  const [cards, setCards] = useState<RadarCard[]>([])
  useEffect(() => {
    fetchRadar(runId).then((d) => setCards(d.cards as RadarCard[])).catch(console.error)
  }, [runId])

  if (cards.length === 0) return <p>暂无板块分析卡。</p>
  return (
    <div>
      {cards.map((c) => (
        <div key={c.sector_id} className="card">
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <h3 style={{ margin: 0 }}>{c.sector_id}</h3>
            <Badge text={c.attribution_level} tone="blue" />
            <span>置信度：{c.confidence}</span>
            <span>上限：{c.allowed_max_level}</span>
          </div>
          <p>{c.conclusion}</p>
          <p>反证：{c.counter_evidence.join('；') || '无'}</p>
          <p>不确定性：{c.uncertainties.join('；') || '无'}</p>
          {c.claims.length > 0 && (
            <ul>
              {c.claims.map((claim) => (
                <li key={claim.claim_id}>{claim.text}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  )
}