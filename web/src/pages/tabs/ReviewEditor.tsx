import { useState } from 'react'
import { applyDraftPatch } from '../../editingApi'

async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('')
}

export default function ReviewEditor(props: {
  runId: string
  draftId: string
  version: number
  sectionId: string
  heading: string
  body: string
  onSaved: () => void
}) {
  const [value, setValue] = useState(props.body)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function save() {
    setSaving(true)
    setError('')
    try {
      await applyDraftPatch(props.runId, props.draftId, {
        base_version: props.version,
        path: `sections/${props.sectionId}/body`,
        old_value_hash: await sha256(props.body),
        new_value: value,
      })
      props.onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card">
      <label htmlFor={`edit-${props.sectionId}`}>{props.heading}</label>
      <textarea id={`edit-${props.sectionId}`} value={value} onChange={(e) => setValue(e.target.value)} rows={5} />
      <button type="button" onClick={save} disabled={saving || value === props.body}>
        {saving ? '保存中…' : '保存修改'}
      </button>
      {error && <p role="alert">{error}</p>}
    </div>
  )
}
