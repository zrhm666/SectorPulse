// web/src/pages/tabs/DraftTab.tsx
import { useEffect, useMemo, useState } from 'react'
import { draftUrl, DraftVersionView, fetchDraft, fetchRun } from '../../api'
import { fetchGovernance, GovernanceResponse } from '../../editingApi'
import GovernanceCard from './GovernanceCard'
import ReviewEditor from './ReviewEditor'

export default function DraftTab({ runId }: { runId: string }) {
  const [versions, setVersions] = useState<DraftVersionView[]>([])
  const [left, setLeft] = useState<number>(0)
  const [right, setRight] = useState<number>(0)
  const [draftId, setDraftId] = useState<string | null>(null)
  const [governance, setGovernance] = useState<GovernanceResponse | null>(null)
  useEffect(() => {
    fetchDraft(runId)
      .then((d) => {
        setVersions(d.versions)
        const vs = d.versions
        if (vs.length > 0) {
          setRight(vs.length)
          if (vs.length > 1) setLeft(vs.length - 1)
        }
      })
      .catch(console.error)
    fetchRun(runId).then((run) => setDraftId(run.draft_id)).catch(console.error)
    fetchGovernance(runId).then(setGovernance).catch(() => setGovernance(null))
  }, [runId])

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
    const res = await fetch(url)
    const text = await res.text()
    await navigator.clipboard.writeText(text)
    alert('已复制到剪贴板')
  }

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
      {draftId && latest.sections[0] && (
        <ReviewEditor
          runId={runId}
          draftId={draftId}
          version={latest.version}
          sectionId={latest.sections[0].section_id}
          heading={latest.sections[0].heading}
          body={latest.sections[0].body}
          onSaved={() => fetchDraft(runId).then((d) => setVersions(d.versions)).catch(console.error)}
        />
      )}
    </div>
  )
}
