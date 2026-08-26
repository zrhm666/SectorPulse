import type { DataRunCandidateView } from '../../dataRunsApi'

type Props = {
  candidates: DataRunCandidateView[]
  selectedIds: string[]
  loading: boolean
  error: string | null
  disabled: boolean
  onToggle: (sectorId: string) => void
  onSelectAll: () => void
  onClear: () => void
}

export default function CandidatesPanel({
  candidates,
  selectedIds,
  loading,
  error,
  disabled,
  onToggle,
  onSelectAll,
  onClear,
}: Props) {
  if (loading) return <p>正在加载候选板块…</p>
  if (error) return <p className="panel-error" role="alert">{error}</p>
  if (candidates.length === 0) return <p>当前没有候选板块。</p>

  const selected = new Set(selectedIds)
  const allSelected = selectedIds.length === candidates.length

  return (
    <section className="candidate-selector" aria-label="候选板块选择">
      <header className="candidate-selector__header">
        <div className="candidate-selector__heading">
          <h3>选择分析板块</h3>
          <p>默认按系统排名全选；生成前可调整，至少保留 3 个。</p>
        </div>
        <output className="candidate-selector__status" aria-live="polite">
          已选择 {selectedIds.length} / {candidates.length}
        </output>
      </header>

      <div className="candidate-selector__toolbar" aria-label="批量选择">
        <button className="button button-secondary" type="button" disabled={disabled || allSelected} onClick={onSelectAll}>
          全部选择
        </button>
        <button className="button button-ghost" type="button" disabled={disabled || selectedIds.length === 0} onClick={onClear}>
          清空选择
        </button>
      </div>

      <ul className="candidate-list candidate-list--selectable">
        {candidates.map((candidate) => {
          const name = candidate.name || candidate.sector_id
          const isSelected = selected.has(candidate.sector_id)
          return (
            <li key={candidate.sector_id} data-selected={isSelected}>
              <label>
                <input
                  type="checkbox"
                  checked={isSelected}
                  disabled={disabled}
                  aria-label={`选择${name}`}
                  onChange={() => onToggle(candidate.sector_id)}
                />
                <span className="candidate-list__rank" aria-label={`排名 ${candidate.rank}`}>{candidate.rank}</span>
                <span className="candidate-list__content">
                  <strong>{name}</strong>
                  <small>{candidate.sector_kind} · 评分 {candidate.score} · {candidate.sector_id}</small>
                  {candidate.reasons.length > 0 && <span className="candidate-list__reasons">{candidate.reasons.join('；')}</span>}
                </span>
              </label>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
