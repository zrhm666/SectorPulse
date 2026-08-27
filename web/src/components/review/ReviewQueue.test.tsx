import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import type { RunSummary } from '../../api'
import ReviewQueue from './ReviewQueue'

const runs: RunSummary[] = [
  { run_id: 'pending-run', requested_at: '2026-08-28T01:00:00Z', provider: 'live', status: 'READY_FOR_HUMAN_REVIEW', elapsed_ms: 1, total_cost_cny: '0', draft_id: 'draft-1' },
  { run_id: 'approved-run', requested_at: '2026-08-27T01:00:00Z', provider: 'fixture', status: 'READY_FOR_HUMAN_REVIEW', elapsed_ms: 1, total_cost_cny: '0', draft_id: 'draft-2', review_decision: 'APPROVED_FOR_COPY' },
]

it('filters the compact queue without changing its selected run', async () => {
  render(<ReviewQueue runs={runs} selectedId="pending-run" onSelect={vi.fn()} />)

  expect(screen.getByRole('button', { name: /pending-run/ })).toHaveAttribute('data-selected', 'true')
  await userEvent.click(screen.getByRole('button', { name: '已批准' }))
  expect(screen.queryByRole('button', { name: /pending-run/ })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /approved-run/ })).toBeVisible()
})
