import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import AnalyticsCard from './AnalyticsCard'

describe('AnalyticsCard', () => {
  it('shows review metrics', () => {
    render(<AnalyticsCard metrics={{ run_id: 'r', review_duration_seconds: 0, patch_count: 2, revision_rounds: 2, governance_failures: 1, approval_count: 1, export_count: 3, llm_cost_cny: 0.5 }} />)
    expect(screen.getByText('修订次数：2')).toBeInTheDocument()
    expect(screen.getByText('导出次数：3')).toBeInTheDocument()
  })
})
