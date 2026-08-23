import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import ConfirmDialog from './ConfirmDialog'

it('focuses cancel first and cancels with Escape', async () => {
  const cancel = vi.fn()
  render(<ConfirmDialog open title="批准 v2" description="确认批准" confirmLabel="批准" onConfirm={vi.fn()} onCancel={cancel} />)
  expect(screen.getByRole('button', { name: '取消' })).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(cancel).toHaveBeenCalledOnce()
})
