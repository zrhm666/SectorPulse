import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { fetchReview } from '../../api'
import ReviewTab from './ReviewTab'

vi.mock('../../api', () => ({ fetchReview: vi.fn() }))

describe('ReviewTab', () => {
  it('distinguishes request failure from a review without issues', async () => {
    vi.mocked(fetchReview)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ decision: null, revision_round: null, issues: [] })

    render(<ReviewTab runId="run-1" />)

    expect(await screen.findByText('无法加载审核结果')).toBeVisible()
    expect(screen.queryByText('无审核问题。')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(await screen.findByText('无审核问题。')).toBeVisible()
  })
})
