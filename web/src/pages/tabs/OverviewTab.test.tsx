import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import OverviewTab from './OverviewTab'

it('does not mark every stage complete for a failed historical run', () => {
  render(<OverviewTab events={[]} done run={{ run_id: 'run-1', requested_at: '2026-08-23T00:00:00Z', provider: 'fixture', status: 'FAILED', elapsed_ms: null, total_cost_cny: null, draft_id: null }} />)

  expect(screen.queryByText('已完成')).not.toBeInTheDocument()
  expect(screen.getAllByText('未完成')).toHaveLength(6)
})
