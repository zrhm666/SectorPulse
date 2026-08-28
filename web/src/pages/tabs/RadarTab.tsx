// web/src/pages/tabs/RadarTab.tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchRadar, RadarCardView } from '../../api'
import Badge from '../../components/Badge'
import InlineAlert from '../../components/ui/InlineAlert'
import LoadingState from '../../components/ui/LoadingState'

export default function RadarTab({ runId }: { runId: string }) {
  const [cards, setCards] = useState<RadarCardView[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const requestId = useRef(0)
  const load = useCallback(async () => {
    const currentRequest = ++requestId.current
    setLoading(true)
    setLoadError(false)
    try {
      const data = await fetchRadar(runId)
      if (currentRequest === requestId.current) setCards(data.cards)
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

  if (loading) return <LoadingState label="正在加载板块雷达…" />
  if (loadError) return <InlineAlert tone="error" title="无法加载板块雷达"><button className="button button-secondary" type="button" onClick={() => void load()}>重新加载</button></InlineAlert>
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
