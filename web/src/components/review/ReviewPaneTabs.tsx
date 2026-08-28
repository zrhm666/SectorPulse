export type ReviewPane = 'queue' | 'draft' | 'evidence'

const PANES: Array<{ id: ReviewPane; label: string }> = [
  { id: 'queue', label: '队列' },
  { id: 'draft', label: '草稿' },
  { id: 'evidence', label: '证据' },
]

export default function ReviewPaneTabs({ active, onChange }: {
  active: ReviewPane
  onChange: (pane: ReviewPane) => void
}) {
  return <div className="review-pane-tabs" role="tablist" aria-label="审核工作区视图">
    {PANES.map((pane) => <button
      key={pane.id}
      id={`review-tab-${pane.id}`}
      type="button"
      role="tab"
      aria-selected={active === pane.id}
      aria-controls={`review-pane-${pane.id}`}
      tabIndex={active === pane.id ? 0 : -1}
      onClick={() => onChange(pane.id)}
    >{pane.label}</button>)}
  </div>
}
