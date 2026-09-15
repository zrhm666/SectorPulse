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

  it('names the draft version the review actually consumed', async () => {
    vi.mocked(fetchReview).mockResolvedValue({
      decision: 'PASS', revision_round: 1, draft_version: 3, issues: [],
    })

    render(<ReviewTab runId="run-1" />)

    // A PASS only means something against the version it reviewed.
    expect(await screen.findByText(/审核版本/)).toBeVisible()
    expect(screen.getByText('第 3 版')).toBeVisible()
  })

  it('says the review version is unrecorded rather than defaulting to the first draft', async () => {
    vi.mocked(fetchReview).mockResolvedValue({
      decision: 'PASS', revision_round: 1, draft_version: null, issues: [],
    })

    render(<ReviewTab runId="run-1" />)

    expect(await screen.findByText(/审核版本/)).toBeVisible()
    expect(screen.getByText('未记录')).toBeVisible()
  })
})
