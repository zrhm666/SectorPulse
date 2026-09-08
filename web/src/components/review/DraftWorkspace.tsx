import { useEffect, useLayoutEffect, useMemo, useRef, useState, type TextareaHTMLAttributes } from 'react'
import type { DraftVersionView } from '../../api'
import type { DraftPatchInput, DraftPatchResponse } from '../../editingApi'
import useDraftAutosave, { type AutosaveStatus } from '../../hooks/useDraftAutosave'

type Editable = { key: string; path: string; label: string; value: string; rows: number; sourceIds?: string[] }

export type DraftFieldContext = { key: string; label: string; sourceIds?: string[] }
export type DraftWorkspaceState = { hasPending: boolean; hasConflict: boolean; readOnly: boolean; version: number }

const STATUS_COPY: Record<AutosaveStatus, string> = {
  clean: '已保存',
  dirty: '等待保存',
  saving: '正在保存',
  saved: '刚刚保存',
  failed: '保存失败',
  conflict: '版本冲突',
}

type Props = {
  versions: DraftVersionView[]
  onSave: (input: DraftPatchInput) => Promise<DraftPatchResponse>
  onPendingChange?: (pending: boolean) => void
  onFocusField?: (field: DraftFieldContext) => void
  onStateChange?: (state: DraftWorkspaceState) => void
}

function DocumentTextarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const fit = () => {
      if (!element.scrollHeight) return
      element.style.height = 'auto'
      element.style.height = `${element.scrollHeight + 2}px`
    }
    fit()
    let width = element.getBoundingClientRect().width
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(entries => {
      const next = entries[0]?.contentRect.width
      if (next != null && next !== width) { width = next; fit() }
    })
    observer?.observe(element)
    return () => observer?.disconnect()
  }, [props.value])
  return <textarea {...props} ref={ref} />
}

export default function DraftWorkspace({ versions, onSave, onPendingChange, onFocusField, onStateChange }: Props) {
  const latest = versions[versions.length - 1]
  const [selected, setSelected] = useState(latest?.version ?? 0)
  useEffect(() => { if (latest) setSelected(latest.version) }, [latest?.version])
  const version = versions.find((item) => item.version === selected) ?? latest
  const definitions = useMemo<Editable[]>(() => version ? [
    { key: 'titles', path: 'titles/0', label: '标题', value: version.titles[0] ?? '', rows: 2 },
    { key: 'introduction', path: 'introduction', label: '导语', value: version.introduction, rows: 4 },
    ...version.sections.map((section) => ({
      key: `sections/${section.section_id}/body`,
      path: `sections/${section.section_id}/body`,
      label: section.heading,
      value: section.body,
      rows: 9,
      sourceIds: section.source_ids,
    })),
    { key: 'conclusion', path: 'conclusion', label: '结论', value: version.conclusion, rows: 5 },
    { key: 'risk_notice', path: 'risk_notice', label: '风险提示', value: version.risk_notice, rows: 3 },
  ] : [], [version])
  const readOnly = Boolean(version && latest && version.version !== latest.version)
  const autosave = useDraftAutosave({
    version: latest?.version ?? 1,
    fields: definitions,
    enabled: Boolean(version) && !readOnly,
    onSave,
  })

  useEffect(() => onPendingChange?.(autosave.hasPending), [autosave.hasPending, onPendingChange])
  useEffect(() => () => onPendingChange?.(false), [onPendingChange])
  useEffect(() => {
    if (version) onStateChange?.({
      hasPending: autosave.hasPending,
      hasConflict: autosave.hasConflict,
      readOnly,
      version: version.version,
    })
  }, [autosave.hasConflict, autosave.hasPending, onStateChange, readOnly, version?.version])

  if (!version) return <main className="draft-workspace" aria-label="草稿编辑区"><p>暂无草稿内容。</p></main>

  return <main className="draft-workspace" aria-label="草稿编辑区">
    <div className="review-pane__header draft-workspace__header">
      <div>
        <p className="draft-workspace__eyebrow">结构化分析草稿</p>
        <h2>{version.titles[0] || '未命名草稿'}</h2>
        <p>{readOnly ? `历史版本 v${version.version}` : `当前编辑版本 v${latest.version}`}</p>
      </div>
      <div className="draft-workspace__tools">
        <output className="draft-save-summary" data-pending={autosave.hasPending} aria-live="polite">
          {readOnly ? '只读' : autosave.hasPending ? '有更改待处理' : '所有更改已保存'}
        </output>
        <label>查看版本<select aria-label="查看草稿版本" value={version.version} disabled={autosave.hasPending} onChange={(event) => setSelected(Number(event.target.value))}>{versions.map((item) => <option key={item.version} value={item.version}>v{item.version}</option>)}</select></label>
      </div>
    </div>
    <label className="draft-chapter-nav">跳转章节<select aria-label="跳转章节" value="" onChange={event => {
      const field = document.getElementById(`field-${event.target.value}`)
      field?.scrollIntoView?.({ block: 'center' })
      field?.focus({ preventScroll: true })
    }}><option value="" disabled>选择要阅读或修改的章节</option>{definitions.map(field => <option key={field.key} value={field.key}>{field.label}</option>)}</select></label>
    {readOnly && <p className="readonly-note">正在查看历史版本 v{version.version}，历史内容不可修改，也不会触发自动保存。</p>}
    <article className="draft-document" aria-label={`草稿版本 v${version.version}`}>
      {definitions.map((field) => {
        const state = autosave.fields[field.key] ?? { value: field.value, status: 'clean' as const, queued: false }
        const needsAttention = state.status === 'failed' || state.status === 'conflict'
        return <section key={field.key} className="draft-document__section" data-save-status={state.status}>
          <div className="draft-document__section-heading">
            <label htmlFor={`field-${field.key}`}>{field.label}</label>
            {!readOnly && <span className="draft-field-status" role="status" data-status={state.status}>{STATUS_COPY[state.status]}{state.queued ? ' · 新修改排队中' : ''}</span>}
          </div>
          <DocumentTextarea
            id={`field-${field.key}`}
            value={state.value}
            readOnly={readOnly}
            rows={field.rows}
            onChange={(event) => autosave.setValue(field.key, event.target.value)}
            onBlur={() => autosave.flush(field.key)}
            onFocus={() => onFocusField?.({ key: field.key, label: field.label, sourceIds: field.sourceIds })}
          />
          {needsAttention && <div className="draft-field-recovery">
            <span>{state.status === 'conflict' ? '本地文本已保留。请基于最新版本重试。' : '本地文本已保留，请检查连接后重试。'}</span>
            <button className="button button-secondary" type="button" onClick={() => autosave.retry(field.key)}>重试保存{field.label}</button>
          </div>}
        </section>
      })}
    </article>
  </main>
}
