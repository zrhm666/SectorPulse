import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { fetchComparisonNews } from '../../runComparisonsApi'
import { newsComparison, pair } from '../../testComparisonFixtures'
import NewsComparisonPanel from './NewsComparisonPanel'

vi.mock('../../runComparisonsApi', () => ({ fetchComparisonNews: vi.fn() }))
beforeEach(() => { vi.resetAllMocks(); vi.mocked(fetchComparisonNews).mockResolvedValue(newsComparison) })
it('keeps missing metadata and same-title IDs, expands text safely and rejects unsafe links', async () => {
  render(<NewsComparisonPanel pair={pair} />)
  expect(await screen.findByText(/新闻元数据不可用/)).toBeVisible()
  expect(screen.getAllByText('同标题新闻')).toHaveLength(2)
  expect(document.body.textContent).toContain('当前保存的新闻元数据')
  const item = screen.getAllByText('同标题新闻')[1].closest('li')!
  fireEvent.click(within(item).getByRole('button', { name: '查看摘要' }))
  expect(screen.getByText('<script>unsafe()</script>')).toBeVisible()
  expect(within(item).queryByRole('link', { name: '查看原文' })).not.toBeInTheDocument()
  expect(item.querySelector('script')).toBeNull()
})
it('uses server totals, resets pagination for filters and offers local retry', async () => {
  vi.mocked(fetchComparisonNews).mockResolvedValueOnce({ ...newsComparison, total: 200 })
  render(<NewsComparisonPanel pair={pair} />)
  await waitFor(() => expect(document.body.textContent).toContain('共 200 条'))
  vi.mocked(fetchComparisonNews).mockRejectedValueOnce(new Error('新闻分页失败'))
  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  await screen.findByText('新闻分页失败')
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  await screen.findByText(/新闻元数据不可用/)
  fireEvent.change(screen.getByLabelText('新闻成员关系'), { target: { value: 'BOTH' } })
  await waitFor(() => expect(fetchComparisonNews).toHaveBeenLastCalledWith(pair, expect.objectContaining({ offset: 0, membership: 'BOTH' }), expect.any(AbortSignal)))
})
it('does not call missing lineage zero news', async () => {
  vi.mocked(fetchComparisonNews).mockResolvedValue({ ...newsComparison, available: false, reason: 'LINEAGE_UNVERIFIABLE', counts: null, total: null, items: [], base_news: { lineage: 'UNVERIFIABLE', recorded_count: 0 } })
  render(<NewsComparisonPanel pair={pair} />)
  expect(await screen.findByText('新闻差异无法核验')).toBeVisible()
  expect(screen.getByText(/未留存成员记录/)).toBeVisible()
  expect(screen.queryByText(/共 0 条/)).not.toBeInTheDocument()
})
it('ignores an old page after the pair changes', async () => {
  let old!: (value: typeof newsComparison) => void
  vi.mocked(fetchComparisonNews).mockReturnValueOnce(new Promise((resolve) => { old = resolve }))
  const view = render(<NewsComparisonPanel pair={pair} />)
  view.rerender(<NewsComparisonPanel pair={{ base: pair.compare, compare: pair.base }} />)
  await screen.findByText(/新闻元数据不可用/)
  await act(async () => old({ ...newsComparison, items: [], total: 999 }))
  expect(screen.queryByText(/999/)).not.toBeInTheDocument()
})
