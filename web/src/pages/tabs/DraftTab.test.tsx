import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { fetchDraft, fetchRun } from '../../api'
import { fetchGovernance, fetchReviewMetrics } from '../../editingApi'
import DraftTab from './DraftTab'

vi.mock('../../api', () => ({
  draftUrl: vi.fn(() => '/api/draft.md'),
  fetchDraft: vi.fn(),
  fetchRun: vi.fn(),
}))
vi.mock('../../editingApi', () => ({ fetchGovernance: vi.fn(), fetchReviewMetrics: vi.fn() }))

describe('DraftTab', () => {
  it('distinguishes request failure from an empty draft and allows retry', async () => {
    vi.mocked(fetchDraft)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ versions: [] })
    vi.mocked(fetchRun).mockResolvedValue({} as never)
    vi.mocked(fetchGovernance).mockRejectedValue(new Error('not ready'))
    vi.mocked(fetchReviewMetrics).mockRejectedValue(new Error('not ready'))

    render(<DraftTab runId="run-1" />)

    expect(await screen.findByText('无法加载草案')).toBeVisible()
    expect(screen.queryByText('暂无草案。')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(await screen.findByText('暂无草案。')).toBeVisible()
  })
})
