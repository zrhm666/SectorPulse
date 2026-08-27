import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { DataRunCandidatePageView } from '../../dataRunsApi'
import CandidatesPanel from './CandidatesPanel'

const page: DataRunCandidatePageView = {
  items: [
    {
      sector_id: '881101', sector_kind: 'INDUSTRY', rank: 1, score: '9.8',
      reasons: ['涨幅领先'], name: '农业', pct_change: '3.2', news_count: 6,
      field_availability: { pct_change: true },
    },
    {
      sector_id: '881102', sector_kind: 'INDUSTRY', rank: 2, score: '8.7',
      reasons: ['成交活跃'], name: '医药', pct_change: null, news_count: 2,
      field_availability: { pct_change: false },
    },
  ],
  total: 22, offset: 0, limit: 20, query: null,
  sort: 'rank', direction: 'asc', data_version: 'a'.repeat(64),
}

function renderPanel(overrides = {}) {
  const props = {
    page,
    selectedIds: ['881101'],
    loading: false,
    error: null,
    disabled: false,
    query: '',
    sort: 'rank' as const,
    direction: 'asc' as const,
    onToggle: vi.fn(),
    onSelectPage: vi.fn(),
    onClear: vi.fn(),
    onQueryChange: vi.fn(),
    onSortChange: vi.fn(),
    onDirectionChange: vi.fn(),
    onPage: vi.fn(),
    ...overrides,
  }
  render(<CandidatesPanel {...props} />)
  return props
}

describe('CandidatesPanel', () => {
  it('renders a compact truthful candidate table', () => {
    renderPanel()

    expect(screen.getByRole('table', { name: '候选板块' })).toBeInTheDocument()
    expect(screen.getByText('农业')).toBeInTheDocument()
    expect(screen.getByText('3.2%')).toBeInTheDocument()
    expect(screen.getByText('未返回')).toBeInTheDocument()
    expect(screen.getByText('6 条')).toBeInTheDocument()
  })

  it('supports search, sorting and current-page selection', async () => {
    const user = userEvent.setup()
    const props = renderPanel()

    fireEvent.change(screen.getByRole('searchbox', { name: '搜索候选板块' }), {
      target: { value: '农业' },
    })
    await user.selectOptions(screen.getByLabelText('候选排序'), 'news_count')
    await user.click(screen.getByRole('button', { name: '降序' }))
    await user.click(screen.getByRole('button', { name: '选择本页' }))

    expect(props.onQueryChange).toHaveBeenLastCalledWith('农业')
    expect(props.onSortChange).toHaveBeenCalledWith('news_count')
    expect(props.onDirectionChange).toHaveBeenCalledWith('desc')
    expect(props.onSelectPage).toHaveBeenCalled()
  })

  it('paginates without discarding off-page selection state', async () => {
    const user = userEvent.setup()
    const props = renderPanel()

    expect(screen.getByText('已选择 1 个')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '下一页' }))

    expect(props.onPage).toHaveBeenCalledWith(20)
  })
})
