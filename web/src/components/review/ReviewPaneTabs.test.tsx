import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import ReviewPaneTabs from './ReviewPaneTabs'

it('exposes the three review panes as an accessible tab switcher', async () => {
  const onChange = vi.fn()
  render(<ReviewPaneTabs active="draft" onChange={onChange} />)

  expect(screen.getByRole('tab', { name: '草稿' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('tab', { name: '队列' })).toHaveAttribute('aria-controls', 'review-pane-queue')
  expect(screen.getByRole('tab', { name: '证据' })).toHaveAttribute('aria-controls', 'review-pane-evidence')

  await userEvent.click(screen.getByRole('tab', { name: '证据' }))
  expect(onChange).toHaveBeenCalledWith('evidence')
})
