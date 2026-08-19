import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import GovernanceCard from './GovernanceCard'

describe('GovernanceCard', () => {
  it('shows passed state and issues', () => {
    render(<GovernanceCard report={{ run_id: 'r', draft_id: 'd', passed: false, issues: [{ code: 'FORBIDDEN_TERM', message: '发现风险用语', severity: 'error' }] }} />)
    expect(screen.getByText('治理未通过')).toBeInTheDocument()
    expect(screen.getByText('发现风险用语')).toBeInTheDocument()
  })
})
