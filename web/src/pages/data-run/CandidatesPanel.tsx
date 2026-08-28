import type { CandidateSort, DataRunCandidatePageView, SortDirection } from '../../dataRunsApi'

type Props = {
  page: DataRunCandidatePageView | null
  selectedIds: string[]
  loading: boolean
  error: string | null
  disabled: boolean
  query: string
  sort: CandidateSort
  direction: SortDirection
  onToggle: (sectorId: string) => void
  onSelectPage: () => void
  onClear: () => void
  onQueryChange: (value: string) => void
  onSortChange: (value: CandidateSort) => void
  onDirectionChange: (value: SortDirection) => void
  onPage: (offset: number) => void
}

function percentage(value: string | null | undefined): string {
  return value == null ? '未返回' : `${value}%`
}

export default function CandidatesPanel({
  page, selectedIds, loading, error, disabled, query, sort, direction,
  onToggle, onSelectPage, onClear, onQueryChange, onSortChange,
  onDirectionChange, onPage,
}: Props) {
  const candidates = page?.items ?? []
  const selected = new Set(selectedIds)
  const allPageSelected = candidates.length > 0
    && candidates.every((candidate) => selected.has(candidate.sector_id))
  const offset = page?.offset ?? 0
  const limit = page?.limit ?? 20
  const total = page?.total ?? 0

  return <section className="candidate-workspace" aria-label="候选板块选择">
    <header className="candidate-workspace__header">
      <div><h3>候选板块</h3><p>选择将进入分析稿的真实候选；确认后才可启动写作。</p></div>
      <output className="candidate-workspace__count" aria-live="polite">已选择 {selectedIds.length} 个</output>
    </header>
    <div className="candidate-workspace__toolbar">
      <label className="candidate-search"><span>搜索候选板块</span><input type="search" value={query} placeholder="名称或板块代码" onChange={(event) => onQueryChange(event.target.value)} /></label>
      <label><span>候选排序</span><select value={sort} onChange={(event) => onSortChange(event.target.value as CandidateSort)}>
        <option value="rank">系统排名</option><option value="score">综合评分</option><option value="pct_change">涨跌幅</option><option value="news_count">新闻覆盖</option><option value="name">板块名称</option>
      </select></label>
      <div className="candidate-direction" role="group" aria-label="排序方向">
        <button type="button" className="button button-secondary" aria-pressed={direction === 'asc'} onClick={() => onDirectionChange('asc')}>升序</button>
        <button type="button" className="button button-secondary" aria-pressed={direction === 'desc'} onClick={() => onDirectionChange('desc')}>降序</button>
      </div>
      <div className="candidate-bulk-actions">
        <button className="button button-secondary" type="button" disabled={disabled || allPageSelected || candidates.length === 0} onClick={onSelectPage}>选择本页</button>
        <button className="button button-ghost" type="button" disabled={disabled || selectedIds.length === 0} onClick={onClear}>清空选择</button>
      </div>
    </div>
    {error && <p className="panel-error" role="alert">{error}</p>}
    <div className="candidate-table-viewport" aria-busy={loading}>
      <table className="candidate-table" aria-label="候选板块"><thead><tr><th scope="col">选择</th><th scope="col">排名 / 板块</th><th scope="col">评分</th><th scope="col">涨跌幅</th><th scope="col">新闻</th><th scope="col">入选依据</th></tr></thead><tbody>
        {loading && candidates.length === 0 && <tr><td colSpan={6} className="candidate-table__empty">正在加载候选板块…</td></tr>}
        {!loading && candidates.length === 0 && <tr><td colSpan={6} className="candidate-table__empty">当前筛选条件下没有候选板块。</td></tr>}
        {candidates.map((candidate) => {
          const name = candidate.name || candidate.sector_id
          const checked = selected.has(candidate.sector_id)
          return <tr key={candidate.sector_id} data-selected={checked}>
            <td data-label="选择"><input type="checkbox" checked={checked} disabled={disabled} aria-label={`选择${name}`} onChange={() => onToggle(candidate.sector_id)} /></td>
            <td data-label="排名 / 板块"><span className="candidate-table__identity"><b>{candidate.rank}</b><span><strong>{name}</strong><small>{candidate.sector_id}</small></span></span></td>
            <td data-label="评分">{candidate.score}</td><td data-label="涨跌幅">{percentage(candidate.pct_change)}</td><td data-label="新闻">{candidate.news_count ?? 0} 条</td><td data-label="入选依据">{candidate.reasons.join('；') || '未记录'}</td>
          </tr>
        })}
      </tbody></table>
    </div>
    <footer className="candidate-pagination"><span>{total === 0 ? '0' : `${offset + 1}–${Math.min(offset + limit, total)}`} / {total}</span>
      <button className="button button-secondary" type="button" disabled={offset === 0 || loading} onClick={() => onPage(Math.max(0, offset - limit))}>上一页</button>
      <button className="button button-secondary" type="button" disabled={offset + limit >= total || loading} onClick={() => onPage(offset + limit)}>下一页</button>
    </footer>
  </section>
}
