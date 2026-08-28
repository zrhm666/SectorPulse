type Props = {
  selectedCount: number
  confirmedVersion: number | null
  dirty: boolean
  saving: boolean
  disabledReason: string | null
  conflict?: boolean
  onConfirm: () => void
  onReset: () => void
  onReloadVersion?: () => void
}

export default function CandidateSelectionBar({ selectedCount, confirmedVersion, dirty, saving, disabledReason, conflict = false, onConfirm, onReset, onReloadVersion }: Props) {
  return <aside className="candidate-selection-bar" aria-label="候选确认状态">
    <div className="candidate-selection-bar__summary"><strong>{selectedCount} 个板块进入分析</strong><span>{confirmedVersion == null ? '尚未确认' : `已确认 v${confirmedVersion}`}</span>{dirty && <span className="candidate-selection-bar__dirty">有未保存修改</span>}</div>
    <div className="candidate-selection-bar__actions">{disabledReason && <small role="status">{disabledReason}</small>}{conflict && onReloadVersion && <button className="button button-secondary" type="button" onClick={onReloadVersion}>加载最新版本并保留选择</button>}<button className="button button-ghost" type="button" disabled={!dirty || saving} onClick={onReset}>撤销本地修改</button><button className="button button-primary" type="button" disabled={Boolean(disabledReason) || !dirty || saving || conflict} onClick={onConfirm}>{saving ? '正在确认…' : `确认 ${selectedCount} 个板块`}</button></div>
  </aside>
}
