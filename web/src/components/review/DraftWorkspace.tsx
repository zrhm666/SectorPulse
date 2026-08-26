import { useEffect, useState } from 'react'
import type { DraftVersionView } from '../../api'

async function hash(value: string) {
  const bytes = new TextEncoder().encode(value)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

type Editable = { key: string; label: string; value: string }

export default function DraftWorkspace({ versions, onSave }: { versions: DraftVersionView[]; onSave: (input: { base_version: number; path: string; old_value_hash: string; value: string }) => Promise<void> }) {
  const latest = versions[versions.length - 1]
  const [selected, setSelected] = useState(latest?.version ?? 0)
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<string | null>(null)
  useEffect(() => { if (latest) setSelected(latest.version) }, [latest?.version])
  const version = versions.find((item) => item.version === selected) ?? latest
  if (!version) return <p>暂无草稿内容。</p>
  const fields: Editable[] = [
    { key: 'titles', label: '标题', value: version.titles[0] ?? '' },
    { key: 'introduction', label: '导语', value: version.introduction },
    ...version.sections.map((section) => ({ key: `sections/${section.section_id}/body`, label: section.heading, value: section.body })),
    { key: 'conclusion', label: '结论', value: version.conclusion },
    { key: 'risk_notice', label: '风险提示', value: version.risk_notice },
  ]
  const readOnly = version.version !== latest.version
  return <main className="draft-workspace" aria-label="草稿编辑区"><div className="review-pane__header"><div><h2>{version.titles[0] || '未命名草稿'}</h2><p>当前编辑版本 v{latest.version}</p></div><label>查看版本<select aria-label="查看草稿版本" value={version.version} onChange={(event) => setSelected(Number(event.target.value))}>{versions.map((item) => <option key={item.version} value={item.version}>v{item.version}</option>)}</select></label></div>{readOnly && <p className="readonly-note">正在查看历史版本 v{version.version}，历史内容不可修改。</p>}<div className="editor-fields">{fields.map((field) => { const value = values[field.key] ?? field.value; return <section key={field.key} className="editor-field"><label htmlFor={`field-${field.key}`}>{field.label}</label><textarea id={`field-${field.key}`} value={value} readOnly={readOnly} rows={field.key.startsWith('sections/') ? 8 : 3} onChange={(event) => setValues((items) => ({ ...items, [field.key]: event.target.value }))} />{!readOnly && <button className="button button-secondary" type="button" disabled={saving !== null || value === field.value} onClick={async () => { setSaving(field.key); try { await onSave({ base_version: latest.version, path: field.key === 'titles' ? 'titles/0' : field.key, old_value_hash: await hash(field.value), value }); setValues({}) } catch { /* The page reports request errors through shared feedback. */ } finally { setSaving(null) } }}>{saving === field.key ? '正在保存…' : `保存${field.label}`}</button>}</section>})}</div></main>
}
