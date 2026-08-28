import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'
import ManagementDrawer from './ManagementDrawer'

it('moves focus into the drawer, closes with Escape and returns focus', async () => {
  const onClosed = vi.fn()
  function Harness() {
    const [open, setOpen] = useState(false)
    return <><button onClick={() => setOpen(true)}>新建计划</button><ManagementDrawer open={open} title="新建调度计划" onClose={() => { setOpen(false); onClosed() }}><input aria-label="计划名称" /></ManagementDrawer></>
  }
  render(<Harness />)
  const trigger = screen.getByRole('button', { name: '新建计划' })
  await userEvent.click(trigger)
  expect(screen.getByRole('dialog', { name: '新建调度计划' })).toBeVisible()
  expect(screen.getByLabelText('计划名称')).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
  expect(onClosed).toHaveBeenCalledOnce()
})
