import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ApprovalCard from './ApprovalCard'

describe('ApprovalCard', () => {
  it('blocks approval while governance has not passed', () => {
    render(<ApprovalCard runId="r" draftId="d" governance={{ run_id: 'r', draft_id: 'd', passed: false, issues: [] }} />)
    expect(screen.getByRole('button', { name: '核准并允许复制' })).toBeDisabled()
  })
})
