// web/src/pages/tabs/DraftTab.tsx
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { draftUrl, DraftVersionView, fetchDraft, fetchRun } from '../../api'
import { fetchGovernance, fetchReviewMetrics, GovernanceResponse, ReviewMetrics } from '../../editingApi'
import GovernanceCard from './GovernanceCard'
import ReviewEditor from './ReviewEditor'
import ApprovalCard from './ApprovalCard'
import AnalyticsCard from './AnalyticsCard'
import { useFeedback } from '../../components/ui/FeedbackProvider'
import InlineAlert from '../../components/ui/InlineAlert'
import LoadingState from '../../components/ui/LoadingState'

export default function DraftTab({ runId }: { runId: string }) {
  const feedback = useFeedback()
  const [versions, setVersions] = useState<DraftVersionView[]>([])
  const [left, setLeft] = useState<number>(0)
  const [right, setRight] = useState<number>(0)
  const [draftId, setDraftId] = useState<string | null>(null)
  const [governance, setGovernance] = useState<GovernanceResponse | null>(null)
  const [metrics, setMetrics] = useState<ReviewMetrics | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const requestId = useRef(0)
  const loadDraft = useCallback(async () => {
    const currentRequest = ++requestId.current
    setLoading(true)
    setLoadError(false)
    try {
      const draft = await fetchDraft(runId)
      if (currentRequest !== requestId.current) return
      setVersions(draft.versions)
      if (draft.versions.length > 0) {
        setRight(draft.versions.length)
        setLeft(draft.versions.length > 1 ? draft.versions.length - 1 : draft.versions.length)
      }
    } catch {
      if (currentRequest === requestId.current) setLoadError(true)
    } finally {
      if (currentRequest === requestId.current) setLoading(false)
    }
  }, [runId])
  useEffect(() => {
    void loadDraft()
    fetchRun(runId).then((run) => setDraftId(run.draft_id)).catch(() => setDraftId(null))
    fetchGovernance(runId).then(setGovernance).catch(() => setGovernance(null))
    fetchReviewMetrics(runId).then(setMetrics).catch(() => setMetrics(null))
    return () => { requestId.current += 1 }
  }, [loadDraft, runId])

  const latest = versions[versions.length - 1]
  const leftV = versions.find((v) => v.version === left)
  const rightV = versions.find((v) => v.version === right)

  const sections = useMemo(() => {
    if (!leftV || !rightV) return []
    return rightV.sections.map((sec) => {
      const lsec = leftV.sections.find((s) => s.section_id === sec.section_id)
      return {
        heading: sec.heading,
        left: lsec?.body ?? '',
        right: sec.body,
        diff: lsec?.body !== sec.body,
      }
    })
  }, [leftV, rightV])

  async function copy(url: string) {
    try {
      const res = await fetch(url)
      if (!res.ok) throw new Error('download failed')
      const text = await res.text()
      await navigator.clipboard.writeText(text)
      feedback.success('已复制到剪贴板。')
    } catch {
      feedback.error('复制失败，请检查浏览器权限或网络连接。')
    }
  }

  if (loading) return <LoadingState label="正在加载草案…" />
  if (loadError) return <InlineAlert tone="error" title="无法加载草案"><button className="button button-secondary" type="button" onClick={() => void loadDraft()}>重新加载</button></InlineAlert>
  if (versions.length === 0) return <p>暂无草案。</p>
  return (
    <div>
      <div className="card">
        <h3>{latest.titles[0]}</h3>
        <p>
          版本 {latest.version}，{latest.status}，{latest.character_count} 字
        </p>
        <h4>导语</h4>
        <p>{latest.introduction}</p>
        <button onClick={() => copy(draftUrl(runId, 'md'))}>复制 Markdown</button>
        <button onClick={() => copy(draftUrl(runId, 'txt'))}>复制纯文本</button>
      </div>
      <div className="card">
        <h4>结论</h4>
        <p>{latest.conclusion}</p>
        <h4>风险提示</h4>
        <p>{latest.risk_notice}</p>
        <h4>来源</h4>
        {latest.sources.length === 0 ? (
          <p>暂无来源</p>
        ) : (
          <ul>
            {latest.sources.map((source, index) => (
              <li key={index}>{String(source.title ?? source.citation_url ?? '未命名来源')}</li>
            ))}
          </ul>
        )}
      </div>
      <div className="card">
        <label>左版本：</label>
        <select value={left} onChange={(e) => setLeft(Number(e.target.value))}>
          {versions.map((v) => (
            <option key={v.version} value={v.version}>
              v{v.version}
            </option>
          ))}
        </select>
        <label>右版本：</label>
        <select value={right} onChange={(e) => setRight(Number(e.target.value))}>
          {versions.map((v) => (
            <option key={v.version} value={v.version}>
              v{v.version}
            </option>
          ))}
        </select>
        {sections.map((s, i) => (
          <div
            key={i}
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8 }}
          >
            <div
              style={{
                background: s.diff ? '#fef3e2' : '#fafafa',
                border: '1px solid #eee',
                padding: 8,
              }}
            >
              <strong>{s.heading}</strong>
              <p style={{ whiteSpace: 'pre-wrap' }}>{s.left}</p>
            </div>
            <div
              style={{
                background: s.diff ? '#eaf6ee' : '#fafafa',
                border: '1px solid #eee',
                padding: 8,
              }}
            >
              <strong>{s.heading}</strong>
              <p style={{ whiteSpace: 'pre-wrap' }}>{s.right}</p>
            </div>
          </div>
        ))}
      </div>
      {governance && <GovernanceCard report={governance} />}
      {metrics && <AnalyticsCard metrics={metrics} />}
      {governance && draftId && (
        <ApprovalCard runId={runId} draftId={draftId} governance={governance} />
      )}
      {draftId && latest.sections[0] && (
        <ReviewEditor
          runId={runId}
          draftId={draftId}
          version={latest.version}
          sectionId={latest.sections[0].section_id}
          heading={latest.sections[0].heading}
          body={latest.sections[0].body}
          onSaved={() => void loadDraft()}
        />
      )}
    </div>
  )
}
