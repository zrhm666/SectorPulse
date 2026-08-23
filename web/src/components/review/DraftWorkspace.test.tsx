import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import DraftWorkspace from './DraftWorkspace'

const versions = [{ version: 1, status: 'READY_FOR_HUMAN_REVIEW', titles: ['标题'], introduction: '导语', sections: [], conclusion: '结论', risk_notice: '风险', sources: [], character_count: 10 }]

it('restores the save control after a failed request', async () => {
  const onSave = vi.fn().mockRejectedValue(new Error('offline'))
  render(<DraftWorkspace versions={versions} onSave={onSave} />)
  const field = screen.getByLabelText('导语')
  await userEvent.clear(field)
  await userEvent.type(field, '新导语')
  await userEvent.click(screen.getByRole('button', { name: '保存导语' }))

  expect(await screen.findByRole('button', { name: '保存导语' })).toBeEnabled()
})
