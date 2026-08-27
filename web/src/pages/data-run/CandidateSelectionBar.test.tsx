import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import CandidateSelectionBar from './CandidateSelectionBar'

describe('CandidateSelectionBar', () => {
  it('shows confirmed version and unsaved local edits', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    const onReset = vi.fn()
    render(<CandidateSelectionBar
      selectedCount={4}
      confirmedVersion={2}
      dirty
      saving={false}
      disabledReason={null}
      onConfirm={onConfirm}
      onReset={onReset}
    />)

    expect(screen.getByText('已确认 v2')).toBeInTheDocument()
    expect(screen.getByText('有未保存修改')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '确认 4 个板块' }))
    await user.click(screen.getByRole('button', { name: '撤销本地修改' }))
    expect(onConfirm).toHaveBeenCalled()
    expect(onReset).toHaveBeenCalled()
  })

  it('explains exactly why confirmation is blocked', () => {
    render(<CandidateSelectionBar
      selectedCount={2}
      confirmedVersion={null}
      dirty
      saving={false}
      disabledReason="至少选择 3 个板块"
      onConfirm={vi.fn()}
      onReset={vi.fn()}
    />)

    expect(screen.getByRole('button', { name: '确认 2 个板块' })).toBeDisabled()
    expect(screen.getByText('至少选择 3 个板块')).toBeInTheDocument()
  })
})
